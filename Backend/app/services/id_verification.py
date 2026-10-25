"""Is a rider applicant's ID real, and is it theirs?

Two layers:
  * free checks, always on: does the number look right for its type, and is the same
    ID already on another application (a common fraud sign)?
  * a government-record check through a licensed provider (Dojah). For a NIN it confirms
    the number exists with NIMC, compares the selfie with the photo NIMC holds (face
    match) and returns the registered name, which we compare with the typed name.
    Dojah's docs don't currently cover Nigerian driver's licences, voter's cards or
    passports, so those are marked for a manual check rather than guessed at.

Only the registered name and the scores are stored. The provider also returns a photo,
date of birth and phone number; none of that is kept."""
import base64
import io
import json
import logging
import re
import unicodedata
from datetime import UTC, datetime
from difflib import SequenceMatcher

import httpx
from PIL import Image
from redis.exceptions import RedisError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.db.redis import redis_client
from app.models.rider_application import (
    ApplicationStatus,
    DocumentKind,
    IdCheckStatus,
    IdType,
    RiderApplication,
    RiderDocument,
)
from app.models.user import User
from app.services import events

log = logging.getLogger(__name__)
S = IdCheckStatus
JOB_QUEUE = "queue:jobs"

# What each ID number should look like. NIN is exact (11 digits); the others are kept
# loose on purpose: a strict pattern that's wrong would flag genuine riders.
FORMATS = {
    IdType.NIN: (re.compile(r"^\d{11}$"), "A NIN has exactly 11 digits"),
    IdType.DRIVERS_LICENCE: (re.compile(r"^[A-Z0-9]{8,15}$"), "Driver's licence numbers are 8-15 letters/digits"),
    IdType.VOTERS_CARD: (re.compile(r"^[A-Z0-9]{16,22}$"), "Voter's card numbers (VIN) are about 19 letters/digits"),
    IdType.PASSPORT: (re.compile(r"^[A-Z]\d{8}$"), "Nigerian passport numbers are a letter and 8 digits"),
}


class ProviderError(Exception):
    """The provider couldn't give an answer (network, keys, balance, rate limit)."""


def _compact(id_number: str) -> str:
    return re.sub(r"[\s-]", "", id_number or "").upper()


def _name_parts(name: str) -> list[str]:
    """Lowercase name parts without accents/tone marks: "Adéwálé Ọlá" -> ["adewale", "ola"]
    (NIMC records are plain capitals; applicants often type the marks)."""
    plain = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    return [p for p in re.split(r"[\s\-'.]+", plain.lower()) if p]


def name_match(typed: str, *registered: str | None) -> int:
    """0-100: how well the typed name matches the government record. Order-insensitive
    (Nigerian records often put the surname first) and forgiving of small spelling slips."""
    typed_parts = _name_parts(typed)
    record_parts = [p for r in registered if r for p in _name_parts(r)]
    if not typed_parts or not record_parts:
        return 0
    # every typed name should appear in the record (a middle name may be missing from the form)
    scores = [max(SequenceMatcher(None, t, r).ratio() for r in record_parts) for t in typed_parts]
    return round(100 * sum(scores) / len(scores))


async def _free_checks(session: AsyncSession, application: RiderApplication) -> list[str]:
    reasons = []
    number = _compact(application.id_number or "")
    if application.id_type and number:
        pattern, rule = FORMATS[application.id_type]
        if not pattern.match(number):
            reasons.append(f"The ID number doesn't look right: {rule}.")
        # the same ID on someone else's application
        others = (await session.exec(
            select(RiderApplication, User).join(User, User.id == RiderApplication.user_id).where(
                RiderApplication.id != application.id, RiderApplication.id_type == application.id_type,
            ))).all()
        for other, user in others:
            if _compact(other.id_number or "") == number:
                reasons.append(f"This ID number is also on {user.full_name}'s application "
                               f"({other.status.value}).")
    return reasons


def _selfie_jpeg_b64(doc: RiderDocument) -> str:
    """Dojah wants a base64 JPEG without the data: prefix; our selfie may be PNG/WebP."""
    with Image.open(io.BytesIO(doc.data)) as img:
        out = io.BytesIO()
        img.convert("RGB").save(out, "JPEG", quality=90)
    return base64.b64encode(out.getvalue()).decode()


async def _dojah_nin_with_selfie(nin: str, selfie_b64: str) -> dict | None:
    """POST /api/v1/kyc/nin/verify. Returns the `entity`, or None if NIMC has no such NIN."""
    if not (settings.DOJAH_APP_ID and settings.DOJAH_SECRET_KEY):
        raise ProviderError("Dojah keys are not set (DOJAH_APP_ID, DOJAH_SECRET_KEY)")
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{settings.DOJAH_BASE_URL.rstrip('/')}/api/v1/kyc/nin/verify",
                             headers={"AppId": settings.DOJAH_APP_ID,
                                      "Authorization": settings.DOJAH_SECRET_KEY},  # no "Bearer"
                             json={"nin": nin, "selfie_image": selfie_b64,
                                   "threshold": settings.ID_FACE_MATCH_THRESHOLD})
    except httpx.HTTPError as e:
        raise ProviderError(f"Could not reach Dojah: {e.__class__.__name__}") from e
    if r.status_code == 404:
        return None
    if r.status_code == 401:
        raise ProviderError("Dojah rejected the keys (check DOJAH_APP_ID / DOJAH_SECRET_KEY and sandbox vs live)")
    if r.status_code == 402:
        raise ProviderError("The Dojah wallet is empty: fund it to keep checking IDs")
    if r.status_code == 429:
        raise ProviderError("Dojah is rate-limiting us; try again in a minute")
    body = r.json() if "json" in r.headers.get("content-type", "") else {}
    if r.status_code == 400:
        message = str(body.get("error") or body.get("message") or "bad request")
        if "not found" in message.lower() or "invalid" in message.lower():
            return None
        raise ProviderError(f"Dojah refused the request: {message[:150]}")
    if r.status_code >= 300 or "entity" not in body:
        raise ProviderError(f"Dojah answered {r.status_code}")
    return body["entity"]


async def check(session: AsyncSession, application: RiderApplication) -> RiderApplication:
    """Runs every check that applies and stores the outcome on the application."""
    user = await session.get(User, application.user_id)
    reasons = await _free_checks(session, application)
    red_flags = bool(reasons)  # a malformed number or an ID already used by someone else
    status, record_name, name_score, face_score = None, None, None, None
    provider = settings.ID_VERIFY_PROVIDER

    if provider == "none":
        status = S.MANUAL
        reasons.append("Automatic government check is off: compare the ID photo with the selfie "
                       "and details by hand (or set up Dojah).")
    elif application.id_type != IdType.NIN:
        status = S.MANUAL
        reasons.append("Automatic checks cover NIN only: verify this ID by hand.")
    else:
        selfie = (await session.exec(select(RiderDocument).where(
            RiderDocument.application_id == application.id,
            RiderDocument.kind == DocumentKind.SELFIE))).first()
        try:
            entity = await _dojah_nin_with_selfie(_compact(application.id_number), _selfie_jpeg_b64(selfie))
        except ProviderError as e:
            status = S.ERROR
            reasons.append(f"Couldn't check with the government record: {e}.")
            entity = None
        if status != S.ERROR:
            if entity is None:
                status = S.FAILED
                reasons.append("This NIN was not found in NIMC records.")
            else:
                first = entity.get("firstname") or entity.get("first_name")
                last = entity.get("surname") or entity.get("last_name")
                middle = entity.get("middlename") or entity.get("middle_name")
                record_name = " ".join(p for p in (first, middle, last) if p).title()[:200] or None
                name_score = name_match(user.full_name, first, middle, last)
                face = entity.get("selfie_verification") or {}
                face_score = face.get("confidence_value")
                face_ok = face.get("match") is True
                if not face_ok:
                    reasons.append(f"The selfie doesn't match the NIN photo well enough "
                                   f"({face_score if face_score is not None else '?'}% vs {settings.ID_FACE_MATCH_THRESHOLD}% needed).")
                if name_score < settings.ID_NAME_MATCH_THRESHOLD:
                    reasons.append(f"The name on the NIN record is “{record_name}”, the applicant "
                                   f"typed “{user.full_name}” ({name_score}% match).")
                status = S.VERIFIED if face_ok and name_score >= settings.ID_NAME_MATCH_THRESHOLD else S.REVIEW

    # a reused or malformed ID always needs a close look, even if the record check passed
    # (or no record check ran)
    if red_flags and status in (S.VERIFIED, S.MANUAL):
        status = S.REVIEW
    application.id_check_status = status
    application.id_check_reasons = reasons
    application.id_record_name, application.id_name_match = record_name, name_score
    application.id_face_match = face_score
    application.id_check_provider = provider
    application.id_checked_at = datetime.now(UTC)
    session.add(application)
    await session.commit()
    await events.publish([events.ADMIN], "rider.id_checked", {
        "application_id": application.id, "full_name": user.full_name, "status": status.value})
    return application


# --------------------------------------------------------------- background job
async def enqueue(application_id) -> None:
    """Checks run in the worker so the applicant doesn't wait on the provider."""
    try:
        await redis_client.lpush(JOB_QUEUE, json.dumps({"type": "id_check", "application_id": str(application_id)}))
    except RedisError:
        log.exception("Could not queue the ID check for application %s", application_id)


async def run_job(session: AsyncSession, job: dict) -> None:
    application = await session.get(RiderApplication, job["application_id"])
    if application and application.status == ApplicationStatus.PENDING:
        await check(session, application)
