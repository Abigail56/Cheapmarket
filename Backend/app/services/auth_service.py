import logging
import uuid
from datetime import UTC, datetime

import jwt
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequest, Conflict, TooManyRequests, Unauthorized
from app.core.security import (
    DUMMY_HASH,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.redis import incr_window
from app.models.rider_application import ApplicationStatus, RiderApplication
from app.models.user import User, UserRole
from app.repositories import user_repo
from app.schemas.auth import RegisterRequest, TokenPair
from app.services import notifications, otp

log = logging.getLogger(__name__)

REVOKED_PREFIX = "jwt:revoked:"
LOGIN_FAILURES_PREFIX = "login:fail:"


async def register(
    session: AsyncSession, data: RegisterRequest, role: UserRole = UserRole.CUSTOMER
) -> User:
    """Public sign-up always passes the default (customer); only the admin endpoint
    POST /admin/users passes another role."""
    if await user_repo.get_by_email(session, data.email):
        raise Conflict("An account with this email already exists", code="email_taken")
    if data.phone and await user_repo.get_by_phone(session, data.phone):
        raise Conflict("An account with this phone number already exists", code="phone_taken")
    user = User(
        email=data.email,
        phone=data.phone,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def _login_id(email: str) -> str:
    """Normalises what someone typed into the login box: lowercase email."""
    email = email.strip()
    return email.lower()


async def _find_user(session: AsyncSession, email: str) -> User | None:
    return await user_repo.get_by_email(session, email)


async def authenticate(
    session: AsyncSession, redis: Redis, email: str, password: str
) -> User:
    login_id = _login_id(email)
    # Keyed by what was typed, not by user id, so unknown accounts lock out the same way
    # (the response never reveals whether an account exists)
    fail_key = f"{LOGIN_FAILURES_PREFIX}{login_id}"
    try:
        failures = int(await redis.get(fail_key) or 0)
        ttl = await redis.ttl(fail_key) if failures >= settings.LOGIN_MAX_FAILURES else 0
    except RedisError:
        # Let people log in while Redis is down; argon2 still makes guessing slow
        log.warning("Redis unavailable, skipping login lockout check")
        failures, redis = 0, None
    if failures >= settings.LOGIN_MAX_FAILURES:
        raise TooManyRequests(
            "Too many failed login attempts, try again later",
            code="login_locked",
            headers={"Retry-After": str(max(ttl, 1))},
        )

    user = await _find_user(session, login_id)
    # Always run one hash verification so timing doesn't reveal whether the account exists
    ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
    if not user or not ok:
        if redis is not None:
            try:
                await incr_window(redis, fail_key, settings.LOGIN_LOCKOUT_SECONDS)
            except RedisError:
                log.warning("Redis unavailable, failed login not counted")
        raise Unauthorized("Incorrect email or password", code="invalid_credentials")
    if redis is not None:
        try:
            await redis.delete(fail_key)
        except RedisError:
            log.warning("Redis unavailable, could not reset login failures")
    await check_can_sign_in(session, user)  # (only reached with the right password)
    return user


async def check_can_sign_in(session: AsyncSession, user: User) -> None:
    """Disabled accounts and riders still waiting for (or refused) approval stay out."""
    if not user.is_active:
        application = (await session.exec(select(RiderApplication).where(
            RiderApplication.user_id == user.id))).first() if user.role == UserRole.RIDER else None
        if application and application.status == ApplicationStatus.PENDING:
            raise Unauthorized("Your rider application is being reviewed. We'll text you when "
                               "it's approved.", code="application_pending")
        if application and application.status == ApplicationStatus.REJECTED:
            raise Unauthorized("Your rider application was not approved. "
                               + (application.reject_reason or ""), code="application_rejected")
        raise Unauthorized("This account is disabled", code="account_disabled")


def issue_tokens(user: User) -> TokenPair:
    access, _, _ = create_token(str(user.id), "access", user.token_version)
    refresh, _, _ = create_token(str(user.id), "refresh", user.token_version)
    return TokenPair(access_token=access, refresh_token=refresh)


async def _revoke(redis: Redis, jti: str, exp: int) -> None:
    ttl = exp - int(datetime.now(UTC).timestamp())
    if ttl > 0:
        await redis.set(f"{REVOKED_PREFIX}{jti}", "1", ex=ttl)


async def is_revoked(redis: Redis, jti: str) -> bool:
    return bool(await redis.exists(f"{REVOKED_PREFIX}{jti}"))


async def refresh(session: AsyncSession, redis: Redis, refresh_token: str) -> TokenPair:
    """Rotates the refresh token: the old one stops working immediately."""
    try:
        payload = decode_token(refresh_token)
    except jwt.PyJWTError:
        raise Unauthorized("Invalid or expired refresh token", code="invalid_token")
    if payload.get("type") != "refresh" or await is_revoked(redis, payload["jti"]):
        raise Unauthorized("Invalid or expired refresh token", code="invalid_token")
    user = await user_repo.get_by_id(session, uuid.UUID(payload["sub"]))
    if not user or not user.is_active or payload.get("ver", 0) != user.token_version:
        raise Unauthorized("Invalid or expired refresh token", code="invalid_token")
    await _revoke(redis, payload["jti"], payload["exp"])
    return issue_tokens(user)


async def logout(redis: Redis, access_payload: dict, refresh_token: str | None) -> None:
    await _revoke(redis, access_payload["jti"], access_payload["exp"])
    if refresh_token:
        try:
            rp = decode_token(refresh_token)
            if rp.get("type") == "refresh" and rp.get("sub") == access_payload["sub"]:
                await _revoke(redis, rp["jti"], rp["exp"])
        except jwt.PyJWTError:
            pass


async def change_password(
    session: AsyncSession, user: User, current: str, new: str
) -> None:
    if not verify_password(current, user.password_hash):
        raise BadRequest("Current password is incorrect", code="wrong_password")
    user.password_hash = hash_password(new)
    session.add(user)
    await session.commit()


# ------------------------------ forgotten password ----------------------------
async def request_password_reset(session: AsyncSession, redis: Redis, email: str) -> None:
    """Emails a reset code if the address belongs to an active account. Says nothing
    either way, so it can't be used to find out who has an account."""
    login_id = _login_id(email)
    user = await _find_user(session, login_id)
    if not user or not user.is_active:
        return
    code = await otp.issue(redis, "reset", login_id)
    await notifications.send_code("email", login_id, code, "reset")


async def reset_password(
    session: AsyncSession, redis: Redis, email: str, code: str, new_password: str
) -> None:
    login_id = _login_id(email)
    if not await otp.verify(redis, "reset", login_id, code):
        raise BadRequest("That code is wrong or has expired. Request a new one.",
                         code="invalid_code")
    user = await _find_user(session, login_id)
    if not user or not user.is_active:
        raise BadRequest("That code is wrong or has expired. Request a new one.",
                         code="invalid_code")
    user.password_hash = hash_password(new_password)
    user.token_version += 1  # signs out every device, including a thief's
    session.add(user)
    await session.commit()
    await redis.delete(f"{LOGIN_FAILURES_PREFIX}{login_id}")  # they proved who they are


# ------------------------------ phone verification ----------------------------
async def request_phone_verification(redis: Redis, user: User) -> None:
    if not user.phone:
        raise BadRequest("Add a phone number to your profile first", code="no_phone")
    if user.phone_verified_at:
        raise BadRequest("Your phone number is already verified", code="already_verified")
    code = await otp.issue(redis, "phone", f"{user.id}:{user.phone}")
    await notifications.send_code("sms", user.phone, code, "phone")


async def confirm_phone_verification(
    session: AsyncSession, redis: Redis, user: User, code: str
) -> User:
    # the code is tied to the number it was sent to, so changing the phone voids it
    if not user.phone or not await otp.verify(redis, "phone", f"{user.id}:{user.phone}", code):
        raise BadRequest("That code is wrong or has expired. Request a new one.",
                         code="invalid_code")
    user.phone_verified_at = datetime.now(UTC)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user
