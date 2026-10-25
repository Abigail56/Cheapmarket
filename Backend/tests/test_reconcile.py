from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app import worker
from app.db.redis import redis_client
from app.db.session import AsyncSessionLocal
from app.models.payment import Payment
from app.services import payment_service, providers
from tests.conftest import queued_messages
from tests.test_payments import card_order, init_paystack


async def _age_payment(reference: str, **delta) -> None:
    async with AsyncSessionLocal() as s:
        await s.exec(update(Payment).where(Payment.reference == reference)
                     .values(created_at=datetime.now(UTC) - timedelta(**delta)))
        await s.commit()


async def _reconcile() -> dict:
    async with AsyncSessionLocal() as s:
        return await payment_service.reconcile_pending(s)


async def _track(client, order) -> dict:
    return (await client.post("/orders/track", json={"order_number": order["order_number"],
                                                     "phone": "08031234567"})).json()


async def test_missed_webhook_is_caught(client, shop, monkeypatch):
    order = await card_order(client, shop)
    init, _ = await init_paystack(client, monkeypatch, order)
    await _age_payment(init["reference"], minutes=10)

    async def verify(reference):
        return {"success": True, "amount_kobo": 650000, "raw": {"reference": reference}}

    monkeypatch.setattr(providers, "paystack_verify", verify)
    stats = await _reconcile()
    assert stats["checked"] == 1 and stats["confirmed"] == 1
    t = await _track(client, order)
    assert t["payment_status"] == "paid" and t["status"] == "confirmed"
    assert any("Payment received" in m["body"] for m in await queued_messages())
    assert (await _reconcile())["checked"] == 0  # nothing left pending


async def test_recent_payments_are_left_for_the_webhook(client, shop, monkeypatch):
    order = await card_order(client, shop)
    await init_paystack(client, monkeypatch, order)  # created just now

    async def verify(reference):
        raise AssertionError("should not be called yet")

    monkeypatch.setattr(providers, "paystack_verify", verify)
    assert (await _reconcile())["checked"] == 0


async def test_gateway_errors_are_retried_later(client, shop, monkeypatch):
    order = await card_order(client, shop)
    init, _ = await init_paystack(client, monkeypatch, order)
    await _age_payment(init["reference"], minutes=10)

    async def verify(reference):
        raise providers.PaymentGatewayError("down")

    monkeypatch.setattr(providers, "paystack_verify", verify)
    stats = await _reconcile()
    assert stats["errors"] == 1 and stats["confirmed"] == 0
    assert (await _track(client, order))["payment_status"] == "unpaid"


async def test_abandoned_payments_expire(client, shop, monkeypatch):
    order = await card_order(client, shop)
    init, _ = await init_paystack(client, monkeypatch, order)
    await _age_payment(init["reference"], hours=49)
    stats = await _reconcile()
    assert stats["expired"] == 1 and stats["checked"] == 0
    async with AsyncSessionLocal() as s:
        p = await payment_service._payment_by_reference(s, init["reference"])
        assert p.status.value == "failed"


async def test_only_one_worker_reconciles_at_a_time():
    await redis_client.set(worker.RECONCILE_LOCK, "1", ex=60)
    assert await worker.reconcile_once() is None
    await redis_client.delete(worker.RECONCILE_LOCK)
    assert await worker.reconcile_once() is not None
