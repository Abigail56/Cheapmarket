import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.api import pages
from app.api.deps import RedisDep, SessionDep
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, configure_sentry
from app.core.middleware import RequestIdMiddleware
from app.db.redis import close_redis
from app.db.session import engine

configure_logging()
configure_sentry()
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.ENVIRONMENT == "production":
        if settings.SMS_BACKEND == "console" or settings.EMAIL_BACKEND == "console":
            log.warning("SMS/email backend is 'console': customers are NOT receiving messages")
        if not settings.SENTRY_DSN:
            log.warning("SENTRY_DSN is not set: errors are only in the logs")
    yield
    await close_redis()
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Cart-Session", "X-Request-ID"],
)
app.add_middleware(RequestIdMiddleware)  # added last = outermost, so it sees everything
register_exception_handlers(app)
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
app.include_router(pages.router)
app.mount("/static", StaticFiles(directory=pages.WEB / "static"), name="static")

if settings.STORAGE_BACKEND == "local":
    Path(settings.MEDIA_DIR).mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")


@app.get("/health", tags=["SYSTEM"])
async def health(session: SessionDep, redis: RedisDep) -> dict[str, str]:
    """Checks that both PostgreSQL and Redis are reachable."""
    await session.exec(text("SELECT 1"))  # type: ignore[call-overload]
    await redis.ping()
    return {"status": "ok", "environment": settings.ENVIRONMENT}
