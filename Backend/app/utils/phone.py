import re

from app.core.config import settings


def normalize_phone(raw: str) -> str:
    """'0803 123 4567' -> '+2348031234567'. Keeps already-international numbers."""
    p = re.sub(r"[\s\-().]", "", raw.strip())
    cc = settings.DEFAULT_PHONE_COUNTRY_CODE
    if p.startswith("+"):
        return p
    if p.startswith("00"):
        return "+" + p[2:]
    if p.startswith("0"):
        return cc + p[1:]
    if p.startswith(cc.lstrip("+")):
        return "+" + p
    return cc + p
