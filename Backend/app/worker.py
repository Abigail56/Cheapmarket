"""Background worker: `python -m app.worker` (the `worker` service in docker-compose).

Three jobs, run side by side:
  * sends queued SMS/emails (retrying failures, see services/notifications.py)
  * every RECONCILE_INTERVAL_SECONDS, re-checks card payments the webhook missed
  * every 15 s, hands deliveries a rider didn't accept in time back to the admin
  * background jobs (checking a rider applicant's ID with the government record)

Run one or several; a Redis lock stops two workers reconciling at the same time,
and each queued message is popped by exactly one worker."""
import asyncio
import json
import logging
import signal

from redis.exceptions import RedisError

from app.core.config import settings
from app.core.logging import configure_logging, configure_sentry
from app.db.redis import SOCKET_TIMEOUT, close_redis, redis_client
from app.db.session import AsyncSessionLocal, engine
from app.services import delivery_service, id_verification, notifications, payment_service

log = logging.getLogger("app.worker")
RECONCILE_LOCK = "lock:reconcile"
EXPIRE_LOCK = "lock:expire-offers"
EXPIRE_INTERVAL_SECONDS = 15


async def process_one_notification(timeout: int = 2) -> bool:
    """Pops and sends one queued message. Returns False if the queue stayed empty."""
    # BRPOP must return before the socket timeout, or an idle queue looks like an outage
    assert timeout < SOCKET_TIMEOUT
    item = await redis_client.brpop([notifications.QUEUE_KEY], timeout=timeout)
    if item is None:
        return False
    msg = json.loads(item[1])
    try:
        await notifications.send(msg)
    except Exception as e:  # any provider failure: retry, then give up loudly
        msg["attempts"] += 1
        if msg["attempts"] < settings.NOTIFICATION_MAX_ATTEMPTS:
            log.warning("%s to %s failed (attempt %d), retrying: %s", msg["channel"],
                        notifications._mask(msg["to"]), msg["attempts"], e)
            await asyncio.sleep(min(2 ** msg["attempts"], 30))
            await redis_client.lpush(notifications.QUEUE_KEY, json.dumps(msg))
        else:
            log.error("Giving up on %s to %s after %d attempts: %s", msg["channel"],
                      notifications._mask(msg["to"]), msg["attempts"], e)
    return True


async def reconcile_once() -> dict[str, int] | None:
    """Runs one reconciliation pass unless another worker holds the lock."""
    lock_ttl = max(settings.RECONCILE_INTERVAL_SECONDS, 60)
    if not await redis_client.set(RECONCILE_LOCK, "1", nx=True, ex=lock_ttl):
        return None
    try:
        async with AsyncSessionLocal() as session:
            stats = await payment_service.reconcile_pending(session)
        if any(stats.values()):
            log.info("Payment reconciliation: %s", stats)
        return stats
    finally:
        await redis_client.delete(RECONCILE_LOCK)


async def expire_offers_once() -> int | None:
    if not await redis_client.set(EXPIRE_LOCK, "1", nx=True, ex=60):
        return None
    try:
        async with AsyncSessionLocal() as session:
            expired = await delivery_service.expire_unaccepted(session)
        if expired:
            log.info("%d delivery offer(s) expired and went back to the admin", expired)
        return expired
    finally:
        await redis_client.delete(EXPIRE_LOCK)


async def _expire_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await expire_offers_once()
        except Exception:
            log.exception("Expiring delivery offers failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=EXPIRE_INTERVAL_SECONDS)
        except TimeoutError:
            pass


async def process_one_job(timeout: int = 2) -> bool:
    """Runs one queued background job. Returns False if there was none."""
    assert timeout < SOCKET_TIMEOUT
    item = await redis_client.brpop([id_verification.JOB_QUEUE], timeout=timeout)
    if item is None:
        return False
    job = json.loads(item[1])
    async with AsyncSessionLocal() as session:
        if job.get("type") == "id_check":
            await id_verification.run_job(session, job)
        else:
            log.warning("Unknown job type %r", job.get("type"))
    return True


async def _job_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await process_one_job()
        except RedisError:
            log.exception("Redis unavailable, job loop waiting")
            await asyncio.sleep(5)
        except Exception:
            log.exception("Background job failed")
            await asyncio.sleep(1)


async def _notification_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await process_one_notification()
        except RedisError:
            log.exception("Redis unavailable, notification loop waiting")
            await asyncio.sleep(5)
        except Exception:
            log.exception("Notification loop error")
            await asyncio.sleep(1)


async def _reconcile_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await reconcile_once()
        except Exception:
            log.exception("Payment reconciliation failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.RECONCILE_INTERVAL_SECONDS)
        except TimeoutError:
            pass


async def main() -> None:
    configure_logging()
    configure_sentry()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    log.info("Worker started (sms=%s, email=%s)", settings.SMS_BACKEND, settings.EMAIL_BACKEND)
    try:
        await asyncio.gather(_notification_loop(stop), _reconcile_loop(stop), _expire_loop(stop),
                             _job_loop(stop))
    finally:
        await close_redis()
        await engine.dispose()
        log.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
