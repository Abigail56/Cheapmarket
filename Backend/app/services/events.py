"""Live events for the admin dashboard, the rider app and the customer's tracking page.

Each audience has its own Redis Stream; pages hold a server-sent-events connection
(GET .../events) and play a sound on the events that matter. Events are published
AFTER the database commit, and carry ids and statuses only: never a delivery code.
If Redis is down, events are skipped (pages also refresh on their own)."""
import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis
from fastapi import Request
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError

from app.core.config import settings
from app.db.redis import redis_client

log = logging.getLogger(__name__)

ADMIN = "events:admin"
MAXLEN = 1000  # each stream keeps roughly the last 1000 events


def rider_stream(rider_id: uuid.UUID | str) -> str:
    return f"events:rider:{rider_id}"


def track_stream(order_id: uuid.UUID | str) -> str:
    return f"events:track:{order_id}"


async def publish(streams: list[str], event: str, data: dict[str, Any]) -> None:
    payload = json.dumps(data, default=str)
    try:
        async with redis_client.pipeline(transaction=False) as pipe:
            for stream in streams:
                pipe.xadd(stream, {"event": event, "data": payload}, maxlen=MAXLEN, approximate=True)
            await pipe.execute()
    except RedisError:
        log.warning("Redis unavailable, live event %s not published", event)


def _sse(event_id: str, event: str, data: str) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {data}\n\n"


async def stream(request: Request, key: str, last_id: str | None = None) -> AsyncIterator[str]:
    """Server-sent events from one Redis Stream until the client disconnects.

    Uses its own connection (not the shared pool): every open page holds one while it
    waits, and they must not starve normal requests. Starts from new events only,
    unless the browser resumes with Last-Event-ID."""
    client = aioredis.from_url(settings.REDIS_URL, decode_responses=True,
                               socket_timeout=30, socket_connect_timeout=5)
    cursor = last_id
    try:
        if cursor is None:
            # a concrete id, not "$": "$" would skip anything published between two reads
            try:
                newest = await client.xrevrange(key, count=1)
            except RedisError:
                newest = []
            cursor = newest[0][0] if newest else "0-0"
        yield "retry: 3000\n\n"  # browsers reconnect after 3 s if the line drops
        # ~2 KB comment: some proxies/tunnels (Cloudflare) hold back a stream until a few KB
        # have passed; this opens the pipe so the first real event isn't stuck behind it
        yield ":" + " " * 2048 + "\n\n"
        while not await request.is_disconnected():
            try:
                records = await client.xread({key: cursor}, block=15_000, count=50)
            except RedisError:
                yield ": redis unavailable\n\n"
                await asyncio.sleep(3)
                continue
            if not records:
                yield ": heartbeat\n\n"  # keeps proxies from closing an idle line
                continue
            for _, entries in records:
                for event_id, fields in entries:
                    cursor = event_id
                    yield _sse(event_id, fields["event"], fields["data"])
    finally:
        await client.aclose()


def response(request: Request, key: str, last_id: str | None) -> StreamingResponse:
    """The HTTP response for a live page. `no-transform` stops proxies and tunnels
    (Cloudflare, nginx) from compressing the stream, which would make them hold events
    back until a buffer fills; X-Accel-Buffering does the same for nginx."""
    return StreamingResponse(stream(request, key, last_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-transform",
                                      "X-Accel-Buffering": "no"})
