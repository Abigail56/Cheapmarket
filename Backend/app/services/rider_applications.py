"""Riders apply in the rider app; an admin approves or rejects them.

An applicant gets a real user account (role rider) that stays inactive, so it can't
sign in, see deliveries or be assigned, until an admin approves the application."""
from datetime import UTC, datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import BadRequest, Conflict, NotFound
from app.core.security import hash_password
from app.models.rider_application import (
    ApplicationStatus,
    DocumentKind,
    RiderApplication,
    RiderDocument,
)
from app.models.user import User, UserRole
from app.repositories import user_repo
from app.schemas.auth import RiderSignup
from app.services import audit, events, id_verification, notifications, storage


async def apply(session: AsyncSession, data: RiderSignup, documents: dict[DocumentKind, bytes],
                *, google_sub: str | None = None) -> RiderApplication:
    for kind in (DocumentKind.ID_FRONT, DocumentKind.SELFIE):
        if not documents.get(kind):
            raise BadRequest(f"Add a photo of your {kind.value.replace('_', ' ')}", code="document_missing")
    # photos are re-encoded on the server (metadata incl. GPS stripped), even if the app didn't
    checked = {kind: await storage.clean_document(blob) for kind, blob in documents.items() if blob}
    if not checked[DocumentKind.SELFIE][0].startswith("image/"):
        raise BadRequest("The face photo must be a photo, not a PDF", code="unsupported_document")
    if await user_repo.get_by_email(session, data.email):
        raise Conflict("This email already has an account. Please use a different email for your rider account.",
                       code="email_taken")
    if await user_repo.get_by_phone(session, data.phone):
        raise Conflict("This phone number already has an account. Please use a different number for your rider account.",
                       code="phone_taken")
    user = User(email=data.email, phone=data.phone, full_name=data.full_name,
                password_hash=hash_password(data.password), role=UserRole.RIDER, is_active=False,
                google_sub=google_sub)
    session.add(user)
    await session.flush()
    application = RiderApplication(user_id=user.id, vehicle_type=data.vehicle_type,
                                   id_type=data.id_type, id_number=data.id_number,
                                   plate_number=data.plate_number, area=data.area, note=data.note)
    session.add(application)
    await session.flush()
    for kind, (content_type, blob) in checked.items():
        session.add(RiderDocument(application_id=application.id, kind=kind,
                                  content_type=content_type, size=len(blob), data=blob))
    await session.commit()
    await id_verification.enqueue(application.id)
    await events.publish([events.ADMIN], "rider.applied", {
        "application_id": application.id, "full_name": user.full_name,
        "vehicle_type": application.vehicle_type.value, "area": application.area})
    await notifications.enqueue("sms", user.phone,
                                "Cheapmarket: thanks for applying to ride with us. We'll text "
                                "you as soon as your account is approved.")
    return application


async def status_for(session: AsyncSession, user: User) -> RiderApplication | None:
    return (await session.exec(select(RiderApplication).where(
        RiderApplication.user_id == user.id))).first()


async def _get_pending(session: AsyncSession, application: RiderApplication) -> User:
    if application.status != ApplicationStatus.PENDING:
        raise Conflict(f"This application was already {application.status.value}",
                       code="already_reviewed")
    return await session.get(User, application.user_id)


async def approve(session: AsyncSession, application: RiderApplication, admin: User) -> RiderApplication:
    user = await _get_pending(session, application)
    application.status = ApplicationStatus.APPROVED
    application.reviewed_by, application.reviewed_at = admin.id, datetime.now(UTC)
    user.is_active = True
    session.add_all([application, user])
    audit.record(session, admin, "rider_application.approve", application,
                 changes={"rider": user.email, "id_check": application.id_check_status.value})
    await session.commit()
    await events.publish([events.ADMIN], "rider.approved",
                         {"application_id": application.id, "full_name": user.full_name})
    if user.phone:
        await notifications.enqueue("sms", user.phone,
                                    "Cheapmarket: you're approved as a rider! Sign in to the "
                                    f"rider app with {user.email} and keep it open to receive deliveries.")
    return application


async def reject(session: AsyncSession, application: RiderApplication, admin: User,
                 reason: str) -> RiderApplication:
    user = await _get_pending(session, application)
    application.status = ApplicationStatus.REJECTED
    application.reviewed_by, application.reviewed_at = admin.id, datetime.now(UTC)
    application.reject_reason = reason
    session.add(application)
    audit.record(session, admin, "rider_application.reject", application,
                 changes={"rider": user.email, "reason": reason})
    await session.commit()
    if user.phone:
        await notifications.enqueue("sms", user.phone,
                                    f"Cheapmarket: sorry, we can't approve your rider application. {reason}")
    return application


async def document_infos(session: AsyncSession, application_ids: list) -> dict:
    """Metadata only (never the file bytes) for the admin list."""
    if not application_ids:
        return {}
    rows = (await session.exec(select(
        RiderDocument.id, RiderDocument.application_id, RiderDocument.kind,
        RiderDocument.content_type, RiderDocument.size,
    ).where(RiderDocument.application_id.in_(application_ids)))).all()
    order = {DocumentKind.ID_FRONT: 0, DocumentKind.ID_BACK: 1, DocumentKind.SELFIE: 2}
    rows = sorted(rows, key=lambda r: order[r[2]])  # front, back, then the face photo
    out: dict = {}
    for doc_id, app_id, kind, content_type, size in rows:
        out.setdefault(app_id, []).append(
            {"id": doc_id, "kind": kind, "content_type": content_type, "size": size})
    return out


async def open_document(session: AsyncSession, application_id, document_id, admin: User) -> RiderDocument:
    """An admin viewing an ID document. Every view is recorded in the audit log."""
    doc = await session.get(RiderDocument, document_id)
    if not doc or doc.application_id != application_id:
        raise NotFound("Document not found")
    audit.record(session, admin, "rider_document.view", entity_type="rider_application",
                 entity_id=application_id, changes={"document": doc.kind.value})
    await session.commit()
    return doc
