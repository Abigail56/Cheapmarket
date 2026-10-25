import json
import logging
import secrets
from datetime import UTC, datetime, timedelta

import httpx
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.models.order import Order, OrderStatus, OrderStatusHistory, PaymentMethod, PaymentStatus
from app.models.payment import Payment, PaymentProvider, PaymentRecordStatus
from app.models.user import User
from app.services import notifications, order_service, providers
from app.services.providers import PaymentGatewayError
from app.utils.money import q2

log = logging.getLogger(__name__)


def _mock_mode() -> bool:
    """Local development without gateway keys: payments can be simulated."""
    return (settings.ENVIRONMENT == "local"
            and not settings.PAYSTACK_SECRET_KEY and not settings.FLUTTERWAVE_SECRET_KEY)


async def initialize(
    session: AsyncSession, order: Order, provider: PaymentProvider
) -> dict:
    if order.payment_method != PaymentMethod.CARD:
        raise BadRequest("This order is not set up for online payment", code="not_card_order")
    if order.payment_status == PaymentStatus.PAID:
        raise BadRequest("This order is already paid", code="already_paid")
    if order.status == OrderStatus.CANCELLED:
        raise BadRequest("This order was cancelled", code="order_cancelled")
    if provider not in (PaymentProvider.PAYSTACK, PaymentProvider.FLUTTERWAVE):
        raise BadRequest("Choose paystack or flutterwave")

    reference = f"{settings.ORDER_NUMBER_PREFIX}-{secrets.token_hex(8).upper()}"
    callback = f"{settings.FRONTEND_URL}/orders/{order.order_number}/payment-complete"

    if _mock_mode():
        result = {"authorization_url": f"{settings.FRONTEND_URL}/mock-pay?reference={reference}",
                  "reference": reference, "mock": True}
    elif provider == PaymentProvider.PAYSTACK:
        result = await providers.paystack_initialize(
            email=order.customer_email, amount=order.total, reference=reference,
            callback_url=callback, order_number=order.order_number)
    else:
        result = await providers.flutterwave_initialize(
            email=order.customer_email, name=order.customer_name, phone=order.customer_phone,
            amount=order.total, reference=reference, redirect_url=callback)

    session.add(Payment(order_id=order.id, provider=provider, reference=reference,
                        amount=order.total, status=PaymentRecordStatus.PENDING))
    await session.commit()
    return result


async def _payment_by_reference(session: AsyncSession, reference: str) -> Payment | None:
    return (await session.exec(select(Payment).where(Payment.reference == reference))).first()


async def confirm_payment(
    session: AsyncSession, payment: Payment, *, paid_kobo: int, raw: dict
) -> Order:
    """Idempotent: safe to call from the webhook AND the verify endpoint."""
    order = await session.get(Order, payment.order_id, with_for_update=True)
    if payment.status == PaymentRecordStatus.SUCCESS:
        return order

    if paid_kobo != int((q2(order.total) * 100).to_integral_value()):
        # Wrong amount (tampering or partial payment): do NOT mark the order paid
        payment.status = PaymentRecordStatus.FAILED
        payment.raw_response = raw
        session.add(payment)
        session.add(OrderStatusHistory(order_id=order.id, status=order.status,
                                       note=f"Payment rejected: amount mismatch ({paid_kobo} kobo)"))
        await session.commit()
        log.warning("Amount mismatch for order %s: paid=%s", order.order_number, paid_kobo)
        return order

    await order_service.set_payment_paid(session, order, payment.provider, payment.reference, raw)
    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.CONFIRMED
        session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.CONFIRMED,
                                       note=f"Payment received via {payment.provider.value}"))
    await session.commit()
    await notifications.order_event(order, "paid")
    return order


async def verify_reference(session: AsyncSession, reference: str) -> Order:
    payment = await _payment_by_reference(session, reference)
    if not payment:
        raise NotFound("Payment not found")
    if payment.status == PaymentRecordStatus.SUCCESS:
        return await session.get(Order, payment.order_id)
    if _mock_mode():
        return await session.get(Order, payment.order_id)  # still pending until simulated
    if payment.provider == PaymentProvider.PAYSTACK:
        result = await providers.paystack_verify(reference)
    elif payment.provider == PaymentProvider.FLUTTERWAVE:
        result = await providers.flutterwave_verify(reference)
    else:
        raise BadRequest("This payment is not verifiable online")
    if not result["success"]:
        return await session.get(Order, payment.order_id)
    return await confirm_payment(session, payment, paid_kobo=result["amount_kobo"], raw=result["raw"])


async def handle_paystack_webhook(session: AsyncSession, raw_body: bytes, signature: str | None) -> None:
    if not providers.paystack_signature_ok(raw_body, signature):
        raise Forbidden("Invalid signature")
    event = json.loads(raw_body)
    if event.get("event") != "charge.success":
        return
    data = event["data"]
    payment = await _payment_by_reference(session, data.get("reference", ""))
    if payment and data.get("status") == "success":
        await confirm_payment(session, payment, paid_kobo=int(data.get("amount", 0)), raw=data)


async def handle_flutterwave_webhook(session: AsyncSession, raw_body: bytes, hash_header: str | None) -> None:
    if not providers.flutterwave_hash_ok(hash_header):
        raise Forbidden("Invalid signature")
    event = json.loads(raw_body)
    data = event.get("data", {})
    reference = data.get("tx_ref", "")
    payment = await _payment_by_reference(session, reference)
    if payment:
        # Never trust the webhook body for the amount: re-verify with Flutterwave
        result = await providers.flutterwave_verify(reference)
        if result["success"]:
            await confirm_payment(session, payment, paid_kobo=result["amount_kobo"], raw=result["raw"])


async def mark_manually_paid(session: AsyncSession, order: Order, actor: User, note: str | None) -> Order:
    """Admin confirms a bank transfer (or cash collected)."""
    if order.payment_status == PaymentStatus.PAID:
        raise BadRequest("This order is already paid")
    if order.status == OrderStatus.CANCELLED:
        raise BadRequest("This order was cancelled")
    provider = {PaymentMethod.TRANSFER: PaymentProvider.TRANSFER,
                PaymentMethod.COD: PaymentProvider.COD}.get(order.payment_method)
    if provider is None:
        raise BadRequest("Card payments are confirmed automatically by the gateway",
                         code="card_order")
    await order_service.set_payment_paid(session, order, provider, None)
    session.add(OrderStatusHistory(order_id=order.id, status=order.status, changed_by=actor.id,
                                   note=note or f"Marked as paid by {actor.full_name}"))
    if order.status == OrderStatus.PENDING:
        order.status = OrderStatus.CONFIRMED
        session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.CONFIRMED,
                                       changed_by=actor.id, note="Payment confirmed"))
    await session.commit()
    await notifications.order_event(order, "paid")
    return order


async def reconcile_pending(session: AsyncSession) -> dict[str, int]:
    """Catches card payments whose webhook never arrived: asks the gateway about every
    payment still pending after RECONCILE_MIN_AGE_SECONDS. Payments pending longer than
    RECONCILE_MAX_AGE_HOURS are marked failed (a late webhook can still confirm them).
    Run by the worker; safe to run often since confirm_payment is idempotent."""
    stats = {"checked": 0, "confirmed": 0, "expired": 0, "errors": 0}
    if _mock_mode():
        return stats
    now = datetime.now(UTC)
    online = Payment.provider.in_([PaymentProvider.PAYSTACK, PaymentProvider.FLUTTERWAVE])
    pending = (Payment.status == PaymentRecordStatus.PENDING) & online
    cutoff = now - timedelta(hours=settings.RECONCILE_MAX_AGE_HOURS)

    expired = (await session.exec(select(Payment).where(pending, Payment.created_at < cutoff))).all()
    for payment in expired:
        payment.status = PaymentRecordStatus.FAILED
        session.add(payment)
    if expired:
        await session.commit()
        stats["expired"] = len(expired)

    due = (await session.exec(select(Payment.reference).where(
        pending, Payment.created_at >= cutoff,
        Payment.created_at <= now - timedelta(seconds=settings.RECONCILE_MIN_AGE_SECONDS),
    ).order_by(Payment.created_at))).all()
    for reference in due:
        stats["checked"] += 1
        try:
            order = await verify_reference(session, reference)
        except (PaymentGatewayError, BadRequest, httpx.HTTPError):  # gateway down: retry next run
            await session.rollback()
            stats["errors"] += 1
            log.warning("Could not verify payment %s, will retry", reference)
            continue
        if order.payment_status == PaymentStatus.PAID:
            stats["confirmed"] += 1
            log.info("Reconciled payment %s for order %s", reference, order.order_number)
    return stats


async def simulate_success(session: AsyncSession, reference: str) -> Order:
    """DEV ONLY (no gateway keys, ENVIRONMENT=local): pretend the gateway confirmed."""
    if not _mock_mode():
        raise NotFound("Not found")
    payment = await _payment_by_reference(session, reference)
    if not payment:
        raise NotFound("Payment not found")
    order = await session.get(Order, payment.order_id)
    return await confirm_payment(session, payment, paid_kobo=int(q2(order.total) * 100),
                                 raw={"simulated": True})
