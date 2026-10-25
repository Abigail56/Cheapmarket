"""'Continue with Google' (Google Identity Services).

The browser shows Google's button; Google hands the page a signed ID token (a JWT); the
page sends it here and we verify it ourselves: signed by Google's current keys, issued by
Google, meant for OUR client ID, not expired, and the email verified by Google. Only then
do we trust the email and name in it. No Google library and no client secret needed."""
import asyncio
import secrets

import jwt
from jwt import PyJWKClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequest, NotFound, Unauthorized
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories import user_repo

GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
_jwks = PyJWKClient(GOOGLE_CERTS, cache_keys=True, lifespan=3600, timeout=10)


def enabled() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID)


def _signing_key(token: str):
    return _jwks.get_signing_key_from_jwt(token).key  # blocking: fetches Google's keys (cached 1 h)


async def verify(token: str) -> dict:
    """The verified claims of a Google ID token, or Unauthorized."""
    if not enabled():
        raise BadRequest("Google sign-in is not set up on this server", code="google_disabled")
    try:
        key = await asyncio.to_thread(_signing_key, token)
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=settings.GOOGLE_CLIENT_ID,
                            issuer=GOOGLE_ISSUERS, leeway=30,
                            options={"require": ["exp", "iat", "iss", "aud", "sub"]})
    except (jwt.PyJWTError, OSError):
        raise Unauthorized("Google sign-in failed. Please try again.", code="google_invalid") from None
    if not claims.get("email") or claims.get("email_verified") is not True:
        raise Unauthorized("Your Google account's email isn't verified", code="google_email_unverified")
    claims["email"] = claims["email"].lower()
    return claims


async def find_or_create(session: AsyncSession, claims: dict, *, create: bool) -> User:
    """The account for this Google identity. Links an existing account with the same
    (Google-verified) email. Creates a CUSTOMER only if `create`; never any other role."""
    user = (await session.exec(select(User).where(User.google_sub == claims["sub"]))).first()
    if user is None:
        user = await user_repo.get_by_email(session, claims["email"])
        if user is not None:
            if user.google_sub and user.google_sub != claims["sub"]:
                raise Unauthorized("This email is linked to a different Google account",
                                   code="google_mismatch")
            user.google_sub = claims["sub"]
            session.add(user)
            await session.commit()
        elif create:
            name = (claims.get("name") or claims["email"].split("@")[0]).strip()[:150]
            user = User(email=claims["email"], full_name=name if len(name) >= 2 else "Customer",
                        google_sub=claims["sub"], role=UserRole.CUSTOMER,
                        # no usable password: they sign in with Google (or reset one by email)
                        password_hash=hash_password(secrets.token_urlsafe(32)))
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            raise NotFound("There's no account for this Google account yet", code="google_no_account")
    return user
