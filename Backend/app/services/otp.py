"""Six-digit one-time codes (password reset, phone verification), kept in Redis.
Only an HMAC of the code is stored; a code works once and dies after
OTP_MAX_ATTEMPTS wrong guesses."""
import hashlib
import hmac
import secrets

from redis.asyncio import Redis

from app.core.config import settings

PREFIX = "otp:"


def _digest(code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


async def issue(redis: Redis, purpose: str, subject: str) -> str:
    """Creates a fresh code (replacing any earlier one) and returns it for sending."""
    code = f"{secrets.randbelow(10**6):06d}"
    key = f"{PREFIX}{purpose}:{subject}"
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(key, mapping={"digest": _digest(code), "attempts": 0})
        pipe.expire(key, settings.OTP_TTL_SECONDS)
        await pipe.execute()
    return code


async def verify(redis: Redis, purpose: str, subject: str, code: str) -> bool:
    """True once for the right code. Wrong guesses count against OTP_MAX_ATTEMPTS."""
    key = f"{PREFIX}{purpose}:{subject}"
    stored = await redis.hget(key, "digest")
    if not stored:
        return False
    if hmac.compare_digest(stored, _digest(code)):
        # single use: if two requests race with the right code, only one deletes it
        return bool(await redis.delete(key))
    if await redis.hincrby(key, "attempts", 1) >= settings.OTP_MAX_ATTEMPTS:
        await redis.delete(key)
    return False
