"""Customer SMS and email.

Requests never talk to the SMS/email provider directly: they push a message onto
a Redis list and the worker (app/worker.py) sends it, retrying failures. So a
slow or broken provider can't slow down or fail a checkout.

Backends are picked in settings: "console" (default) only logs the message, so
everything works locally without keys; "termii" / "smtp" send for real."""
import asyncio
import json
import logging
import smtplib
from email.message import EmailMessage
from typing import Literal

import httpx
from redis.exceptions import RedisError

from app.core.config import settings
from app.db.redis import redis_client
from app.models.order import Order, OrderStatus
from app.utils.money import q2

log = logging.getLogger(__name__)

QUEUE_KEY = "queue:notifications"
Channel = Literal["sms", "email", "push"]


class NotificationError(Exception):
    pass


# ---------------------------------- queueing ----------------------------------
async def enqueue(channel: Channel, to: str, body: str, subject: str = "", **extra: str) -> None:
    msg = {"channel": channel, "to": to, "subject": subject, "body": body, "attempts": 0, **extra}
    try:
        await redis_client.lpush(QUEUE_KEY, json.dumps(msg))
    except RedisError:
        # The order/reset itself already succeeded; losing one message is the lesser evil
        log.error("Redis unavailable, dropped %s notification to %s", channel, _mask(to))


def _mask(to: str) -> str:
    return to[:3] + "***" + to[-2:] if len(to) > 6 else "***"


# ---------------------------------- sending -----------------------------------
async def send(msg: dict) -> None:
    """Delivers one queued message. Raises NotificationError on failure."""
    if msg["channel"] == "sms":
        await _send_sms(msg["to"], msg["body"])
    elif msg["channel"] == "push":
        from app.services import push  # push needs the database; keep it out of import time
        sent, failed = await push.send_to_user(msg["to"], {
            "title": msg["subject"], "body": msg["body"], "url": msg.get("url"),
            "tag": msg.get("tag"), "urgency": msg.get("urgency")})
        if failed and not sent:
            raise NotificationError(f"push failed on all {failed} device(s)")
    else:
        await _send_email(msg["to"], msg["subject"], msg["body"])


async def _send_sms(phone: str, text: str) -> None:
    if settings.SMS_BACKEND == "console":
        log.info("SMS to %s: %s", phone, text)
        return
    if not settings.TERMII_API_KEY:
        raise NotificationError("TERMII_API_KEY is not set")
    body = {"api_key": settings.TERMII_API_KEY, "to": phone.lstrip("+"),
            "from": settings.TERMII_SENDER_ID, "sms": text, "type": "plain", "channel": "generic"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{settings.TERMII_BASE_URL}/api/sms/send", json=body)
    except httpx.HTTPError as e:
        raise NotificationError(f"Termii request failed: {e}") from e
    if r.status_code >= 300:
        raise NotificationError(f"Termii returned {r.status_code}: {r.text[:200]}")


async def _send_email(to: str, subject: str, text: str) -> None:
    if settings.EMAIL_BACKEND == "console":
        log.info("Email to %s: %s\n%s", to, subject, text)
        return
    if not settings.SMTP_HOST:
        raise NotificationError("SMTP_HOST is not set")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.EMAIL_FROM, to, subject
    msg.set_content(text)

    def _deliver() -> None:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as s:
            if settings.SMTP_STARTTLS:
                s.starttls()
            if settings.SMTP_USER:
                s.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            s.send_message(msg)

    try:
        await asyncio.to_thread(_deliver)  # smtplib blocks; keep the event loop free
    except (OSError, smtplib.SMTPException) as e:
        raise NotificationError(f"SMTP send failed: {e}") from e


# ------------------------------ message templates -----------------------------
OrderEvent = Literal["placed", "paid", "confirmed", "out_for_delivery", "delivered", "cancelled",
                     "rider_accepted", "rider_arrived"]

_ORDER_TEXT: dict[str, str] = {
    "placed": "Thanks for your order {n} ({total}). Track it here: {link}",
    "paid": "Payment received for order {n} ({total}). We're getting it ready.",
    "confirmed": "Your order {n} is confirmed and being prepared.",
    "out_for_delivery": "Your order {n} is on its way to you. Watch the rider live: {link}",
    "delivered": "Your order {n} has been delivered. Enjoy, and thanks for shopping with us!",
    "cancelled": "Your order {n} has been cancelled. Questions? Just reply or call us.",
    "rider_accepted": "{rider} is your rider for order {n}. Track it live: {link}",
    "rider_arrived": "Your rider has arrived with order {n}. They will ask for the delivery code we text you.",
}
_ORDER_SUBJECT: dict[str, str] = {
    "placed": "We received your order {n}",
    "paid": "Payment received for {n}",
    "confirmed": "Order {n} confirmed",
    "out_for_delivery": "Order {n} is on its way",
    "delivered": "Order {n} delivered",
    "cancelled": "Order {n} cancelled",
    "rider_accepted": "A rider is bringing order {n}",
    "rider_arrived": "Your rider has arrived with {n}",
}
# order status changes that the customer hears about
STATUS_EVENTS: dict[OrderStatus, OrderEvent] = {
    OrderStatus.CONFIRMED: "confirmed",
    OrderStatus.OUT_FOR_DELIVERY: "out_for_delivery",
    OrderStatus.DELIVERED: "delivered",
    OrderStatus.CANCELLED: "cancelled",
}


def tracking_url(order: Order) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/track/{order.tracking_token}"


async def order_event(order: Order, event: OrderEvent, **extra: str) -> None:
    fmt = {"n": order.order_number, "total": f"{settings.CURRENCY} {q2(order.total):,}",
           "link": tracking_url(order), **extra}
    text = _ORDER_TEXT[event].format(**fmt)
    await enqueue("sms", order.customer_phone, f"Cheapmarketdeal: {text}")
    if order.customer_email:
        await enqueue("email", order.customer_email, text,
                      subject=_ORDER_SUBJECT[event].format(**fmt))


async def push_rider(rider_id, title: str, body: str, *, tag: str, url: str = "/rider/") -> None:
    """Alert on the rider's phone even when the app is closed (if they turned alerts on).
    `tag` groups alerts: a newer one with the same tag replaces the old one."""
    await enqueue("push", str(rider_id), body, subject=title, url=url, tag=tag, urgency="high")


async def send_code(channel: Channel, to: str, code: str, purpose: str) -> None:
    minutes = settings.OTP_TTL_SECONDS // 60
    what = {"reset": "reset your password", "phone": "verify your phone number"}[purpose]
    text = f"Your Cheapmarketdeal code is {code}. Use it to {what}. It expires in {minutes} minutes."
    await enqueue(channel, to, text, subject="Your Cheapmarketdeal code")
