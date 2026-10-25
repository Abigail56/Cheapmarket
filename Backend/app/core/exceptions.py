import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.logging import request_id_var

log = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, headers: dict | None = None):
        self.message = message
        self.headers = headers
        if code:
            self.code = code
        super().__init__(message)


class BadRequest(AppError):
    status_code, code = 400, "bad_request"


class Unauthorized(AppError):
    status_code, code = 401, "unauthorized"


class Forbidden(AppError):
    status_code, code = 403, "forbidden"


class NotFound(AppError):
    status_code, code = 404, "not_found"


class Conflict(AppError):
    status_code, code = 409, "conflict"


class TooManyRequests(AppError):
    status_code, code = 429, "rate_limited"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Logged at ERROR with the traceback, which Sentry also picks up
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        rid = request_id_var.get()
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error",
                               "message": "Something went wrong on our side. Please try again.",
                               "request_id": rid}},
            headers={"X-Request-ID": rid} if rid else None,
        )
