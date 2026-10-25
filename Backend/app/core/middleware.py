import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

access_log = logging.getLogger("app.access")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIdMiddleware:
    """Gives every request an id (the caller's X-Request-ID if sane, else a new one),
    puts it on every log line and on the response, and writes one access-log line.
    Plain ASGI rather than BaseHTTPMiddleware so the id stays visible to the
    exception handlers, which run in the same task."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _SAFE_ID.match(incoming) else uuid.uuid4().hex
        request_id_var.set(rid)
        start = time.perf_counter()
        status = 500

        async def _send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            access_log.info(
                "%s %s %s", scope["method"], scope["path"], status,
                extra={"method": scope["method"], "path": scope["path"], "status": status,
                       "duration_ms": round((time.perf_counter() - start) * 1000, 1)},
            )
