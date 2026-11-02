"""The notification bell: a saved list of what happened, per admin and per rider.

Live events vanish once they've played; the bell keeps them, so someone who was away
still sees what they missed. Events become bell lines here (see events.publish), so a new
alert only needs a line in ADMIN_TEXT or RIDER_TEXT. Never put a delivery code in one."""
import logging
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.notification import Notification
from app.models.user import User, UserRole

log = logging.getLogger(__name__)
KEEP_DAYS = 30

Text = Callable[[dict[str, Any]], tuple[str, str] | None]


def _money(amount: Any) -> str:
    return f"₦{float(amount):,.2f}".removesuffix(".00")


_PAYMENT = {"cod": "pay on delivery", "card": "card", "transfer": "bank transfer"}


def _admin_status(d: dict) -> tuple[str, str] | None:
    return ("Order cancelled", f"{d['order_number']} was cancelled.") if d["status"] == "cancelled" else None


def _rider_status(d: dict) -> tuple[str, str] | None:
    return (("Order cancelled", f"{d['order_number']} was cancelled. Please don't deliver it.")
            if d["status"] == "cancelled" else None)


ADMIN_TEXT: dict[str, Text] = {
    "order.placed": lambda d: (
        "New order",
        f"{d['order_number']}: {_money(d['total'])}, {_PAYMENT.get(d['payment_method'], d['payment_method'])}."),
    "order.status_changed": _admin_status,
    "delivery.accepted": lambda d: ("Rider accepted", f"{d['rider_name']} is taking {d['order_number']}."),
    "delivery.declined": lambda d: (
        "Rider declined",
        f"{d['rider_name']} can't take {d['order_number']}"
        + (f": {d['reason']}" if d.get("reason") else ".") + " It needs a new rider."),
    "delivery.expired": lambda d: (
        "No answer from rider", f"Nobody accepted {d['order_number']} in time. It needs a new rider."),
    "delivery.code_wrong": lambda d: (
        "Wrong delivery code", f"A wrong code was entered for {d['order_number']} ({d['attempts']} so far)."),
    "delivery.failed": lambda d: ("Delivery failed", f"{d['order_number']}: {d['reason']}"),
    "delivery.delivered": lambda d: ("Delivered", f"{d['rider_name']} delivered {d['order_number']}."),
    "delivery.address_corrected": lambda d: (
        "Address updated", f"The customer changed the address for {d['order_number']}."),
    "rider.applied": lambda d: ("New rider application", f"{d['full_name']} wants to ride with us."),
}

RIDER_TEXT: dict[str, Text] = {
    "delivery.assigned": lambda d: ("New delivery for you", f"{d['order_number']} is waiting for you to accept."),
    "delivery.expired": lambda d: ("Offer ended", f"The time to accept {d['order_number']} ran out."),
    "delivery.unassigned": lambda d: ("Delivery reassigned", f"{d['order_number']} went to another rider."),
    "delivery.address_corrected": lambda d: (
        "Address changed",
        f"The customer changed the address for {d['order_number']}. Please check it and confirm again."),
    "delivery.geofence_overridden": lambda d: (
        "Location check waived", f"You can finish {d['order_number']} without the distance check."),
    "order.status_changed": _rider_status,
}


async def record(event: str, data: dict[str, Any], *, admins: bool, rider_ids: Iterable[str]) -> None:
    """Saves the bell lines for one live event. Runs after the real work has committed and on
    its own session, so a problem here can never undo or fail an order."""
    admin_text = ADMIN_TEXT[event](data) if admins and event in ADMIN_TEXT else None
    rider_text = RIDER_TEXT[event](data) if event in RIDER_TEXT else None
    rider_ids = list(rider_ids) if rider_text else []
    if not admin_text and not rider_ids:  # most events (GPS pings above all) stop here
        return
    order_number = data.get("order_number")
    try:
        async with AsyncSessionLocal() as session:
            if admin_text:
                ids = (await session.exec(select(User.id).where(
                    User.role == UserRole.ADMIN, User.is_active.is_(True)))).all()
                session.add_all(_rows(ids, event, admin_text, order_number))
            if rider_text:
                session.add_all(_rows([uuid.UUID(r) for r in rider_ids], event, rider_text, order_number))
            await session.commit()
    except Exception:
        log.exception("Could not save the bell notification for %s", event)


def _rows(user_ids, kind: str, text: tuple[str, str], order_number: str | None) -> list[Notification]:
    title, body = text
    return [Notification(user_id=uid, kind=kind, title=title[:150], body=body[:500],
                         order_number=order_number) for uid in user_ids]


async def unread_count(session: AsyncSession, user: User) -> int:
    return (await session.exec(select(func.count()).select_from(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)))).one()


async def latest(session: AsyncSession, user: User, limit: int) -> list[Notification]:
    return list((await session.exec(select(Notification).where(Notification.user_id == user.id)
                                    .order_by(Notification.created_at.desc()).limit(limit))).all())


async def mark_read(session: AsyncSession, user: User, notification_id: uuid.UUID) -> bool:
    """False if it isn't this person's notification."""
    row = await session.get(Notification, notification_id)
    if not row or row.user_id != user.id:
        return False
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
        session.add(row)
        await session.commit()
    return True


async def mark_all_read(session: AsyncSession, user: User) -> None:
    await session.exec(update(Notification).where(
        Notification.user_id == user.id, Notification.read_at.is_(None)
    ).values(read_at=datetime.now(UTC)))
    await session.commit()


async def prune(session: AsyncSession) -> None:
    """Worker job: the bell is a recent history, not an archive."""
    await session.exec(delete(Notification).where(
        Notification.created_at < datetime.now(UTC) - timedelta(days=KEEP_DAYS)))
    await session.commit()
