import logging
import uuid
from typing import Annotated, NamedTuple

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.exceptions import Forbidden, TooManyRequests, Unauthorized
from app.core.security import decode_token
from app.db.redis import get_redis, incr_window
from app.db.session import get_session
from app.models.user import User, UserRole
from app.repositories import user_repo
from app.services.auth_service import is_revoked

log = logging.getLogger(__name__)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
RedisDep = Annotated[Redis, Depends(get_redis)]

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Paste the access_token from /auth/login (without the 'Bearer ' prefix)",
)
BearerCreds = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)]


class AuthContext(NamedTuple):
    user: User
    payload: dict


async def _resolve(session: AsyncSession, redis: Redis, token: str) -> AuthContext:
    try:
        payload = decode_token(token)
    except jwt.PyJWTError:
        raise Unauthorized("Invalid or expired token", code="invalid_token")
    if payload.get("type") != "access":
        raise Unauthorized("Invalid or expired token", code="invalid_token")
    try:
        revoked = await is_revoked(redis, payload["jti"])
    except RedisError:
        # Access tokens live 30 minutes, so briefly honouring a logged-out one beats
        # locking every customer out while Redis is down
        log.warning("Redis unavailable, skipping token revocation check")
        revoked = False
    if revoked:
        raise Unauthorized("Invalid or expired token", code="invalid_token")
    user = await user_repo.get_by_id(session, uuid.UUID(payload["sub"]))
    if not user or not user.is_active or payload.get("ver", 0) != user.token_version:
        raise Unauthorized("Invalid or expired token", code="invalid_token")
    return AuthContext(user, payload)


async def get_auth_context(
    session: SessionDep, redis: RedisDep, creds: BearerCreds
) -> AuthContext:
    if not creds or not creds.credentials:
        raise Unauthorized("Not authenticated", code="not_authenticated")
    return await _resolve(session, redis, creds.credentials)


async def get_current_user(ctx: Annotated[AuthContext, Depends(get_auth_context)]) -> User:
    return ctx.user


async def get_optional_user(
    session: SessionDep, redis: RedisDep, creds: BearerCreds
) -> User | None:
    """For routes that work for guests and logged-in users (cart, checkout)."""
    if not creds or not creds.credentials:
        return None
    return (await _resolve(session, redis, creds.credentials)).user


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != UserRole.ADMIN:
        raise Forbidden("Admin access required")
    return user


async def require_rider(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role not in (UserRole.RIDER, UserRole.ADMIN):
        raise Forbidden("Rider access required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
AdminUser = Annotated[User, Depends(require_admin)]
RiderUser = Annotated[User, Depends(require_rider)]


def rate_limit(name: str, limit: int, window: int = 60):
    """Fixed-window limiter per client IP. Behind a proxy, set FORWARDED_ALLOW_IPS to the
    proxy's address so request.client.host is the real client. Skipped if Redis is down."""

    async def _dep(request: Request, redis: RedisDep) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        ip = request.client.host if request.client else "unknown"
        key = f"rl:{name}:{ip}"
        try:
            count = await incr_window(redis, key, window)
            ttl = await redis.ttl(key) if count > limit else 0
        except RedisError:
            log.warning("Redis unavailable, skipping rate limit %s", name)
            return
        if count > limit:
            raise TooManyRequests(
                "Too many requests, please slow down",
                headers={"Retry-After": str(max(ttl, 1))},
            )

    return _dep


class CartOwner(NamedTuple):
    user: User | None
    session_id: str | None


async def get_cart_owner(
    user: OptionalUser,
    x_cart_session: Annotated[str | None, Header()] = None,
) -> CartOwner:
    return CartOwner(user, x_cart_session)


CartOwnerDep = Annotated[CartOwner, Depends(get_cart_owner)]