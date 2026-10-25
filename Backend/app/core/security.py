import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

_hasher = PasswordHash.recommended()  # argon2id
# Verified against when the user doesn't exist, so response time doesn't reveal valid emails
DUMMY_HASH = _hasher.hash("not-a-real-password")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(password, hashed)
    except Exception:
        return False


def create_token(
    subject: str, token_type: TokenType, version: int = 0
) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at). `version` is the user's token_version."""
    now = datetime.now(UTC)
    if token_type == "access":
        exp = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    else:
        exp = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    jti = uuid.uuid4().hex
    payload = {"sub": subject, "type": token_type, "jti": jti, "ver": version,
               "iat": now, "exp": exp}
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, jti, exp


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError if invalid/expired."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
