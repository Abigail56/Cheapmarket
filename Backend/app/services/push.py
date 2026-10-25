"""Web push to the rider app, so offers reach a rider whose app is closed.

Standard Web Push (RFC 8030/8291/8292) with our own VAPID keys: no Firebase account.
Payloads are encrypted to each browser's key; the push service (Google, Mozilla,
Apple) only relays them. Sending happens in the worker, via the notification queue."""
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from urllib.parse import urlsplit

import requests
from pywebpush import WebPushException, webpush
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequest
from app.db.session import AsyncSessionLocal
from app.models.push_subscription import PushSubscription
from app.models.user import User

log = logging.getLogger(__name__)
_http = requests.Session()  # reused connection to the push services


def enabled() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def _allowed_endpoint(endpoint: str) -> bool:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        return False
    return any(host == h.lstrip(".") or (h.startswith(".") and host.endswith(h))
               for h in settings.PUSH_ALLOWED_HOSTS)


async def subscribe(session: AsyncSession, user: User, *, endpoint: str, p256dh: str, auth: str,
                    user_agent: str | None) -> PushSubscription:
    if not enabled():
        raise BadRequest("Push notifications are not set up on this server", code="push_disabled")
    if not _allowed_endpoint(endpoint):
        raise BadRequest("That is not a browser push address", code="bad_push_endpoint")
    existing = (await session.exec(select(PushSubscription).where(
        PushSubscription.endpoint == endpoint))).first()
    sub = existing or PushSubscription(user_id=user.id, endpoint=endpoint, p256dh=p256dh, auth=auth)
    # the same phone may change hands (another rider logs in): it now belongs to this user
    sub.user_id, sub.p256dh, sub.auth = user.id, p256dh, auth
    sub.user_agent = (user_agent or "")[:300] or None
    session.add(sub)
    await session.commit()
    return sub


async def unsubscribe(session: AsyncSession, user: User, endpoint: str) -> None:
    sub = (await session.exec(select(PushSubscription).where(
        PushSubscription.endpoint == endpoint, PushSubscription.user_id == user.id))).first()
    if sub:
        await session.delete(sub)
        await session.commit()


def _send_one(sub: PushSubscription, payload: str, urgency: str) -> int:
    """Blocking HTTP call (run in a thread). Returns the push service's status code."""
    try:
        resp = webpush(
            subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            ttl=10 * 60,  # an offer is useless after its 5-minute window anyway
            headers={"Urgency": urgency},
            timeout=10,
            requests_session=_http,
        )
        return resp.status_code
    except WebPushException as e:
        return e.response.status_code if e.response is not None else 0


async def send_to_user(user_id: str | uuid.UUID, message: dict) -> tuple[int, int]:
    """Push to every device of a user. Returns (accepted, temporary failures). Subscriptions
    the push service says are gone (404/410: app uninstalled, alerts off) are deleted."""
    if not enabled():
        return 0, 0
    payload = json.dumps({k: message.get(k) for k in ("title", "body", "url", "tag")})
    urgency = message.get("urgency") or "high"
    sent = failed = 0
    async with AsyncSessionLocal() as session:
        subs = (await session.exec(select(PushSubscription).where(
            PushSubscription.user_id == uuid.UUID(str(user_id))))).all()
        for sub in subs:
            status = await asyncio.to_thread(_send_one, sub, payload, urgency)
            if 200 <= status < 300:
                sent += 1
                sub.last_success_at = datetime.now(UTC)
                session.add(sub)
            elif status in (404, 410):
                log.info("Push subscription %s is gone (%s), removing it", sub.id, status)
                await session.delete(sub)
            else:
                failed += 1
                log.warning("Push to subscription %s failed with status %s", sub.id, status)
        await session.commit()
    return sent, failed
