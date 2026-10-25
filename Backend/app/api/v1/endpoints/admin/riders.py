import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import AdminUser, SessionDep
from app.core.exceptions import NotFound
from app.models.rider_application import ApplicationStatus, RiderApplication
from app.models.user import User
from app.schemas.admin import RejectApplication, RiderApplicationRead
from app.services import audit, id_verification, rider_applications
from app.utils.pagination import Page, PageParams

router = APIRouter(prefix="/admin/rider-applications", tags=["admin: riders"])


def _read(application: RiderApplication, user: User, documents: list | None = None) -> RiderApplicationRead:
    return RiderApplicationRead(
        **application.model_dump(include={"id", "vehicle_type", "id_type", "id_number", "plate_number",
                                          "area", "note", "status", "created_at", "reviewed_at",
                                          "reject_reason", "id_check_status", "id_check_reasons",
                                          "id_record_name", "id_name_match", "id_face_match",
                                          "id_checked_at"}),
        full_name=user.full_name, email=user.email, phone=user.phone, documents=documents or [])


async def _get(session, application_id: uuid.UUID) -> RiderApplication:
    application = await session.get(RiderApplication, application_id, with_for_update=True)
    if not application:
        raise NotFound("Application not found")
    return application


@router.get("", response_model=Page[RiderApplicationRead])
async def list_applications(_: AdminUser, session: SessionDep,
                            params: Annotated[PageParams, Depends()],
                            status: ApplicationStatus | None = ApplicationStatus.PENDING):
    """People who applied in the rider app (pending first by default; pass status= for others)."""
    conds = [RiderApplication.status == status] if status else []
    total = (await session.exec(select(func.count()).select_from(RiderApplication).where(*conds))).one()
    rows = (await session.exec(
        select(RiderApplication, User).join(User, User.id == RiderApplication.user_id)
        .where(*conds).order_by(RiderApplication.created_at)
        .offset(params.offset).limit(params.size))).all()
    docs = await rider_applications.document_infos(session, [a.id for a, _ in rows])
    return Page[RiderApplicationRead].build([_read(a, u, docs.get(a.id)) for a, u in rows], total, params)


@router.post("/{application_id}/approve", response_model=RiderApplicationRead)
async def approve(application_id: uuid.UUID, admin: AdminUser, session: SessionDep):
    """Activates the rider: they can sign in and be assigned deliveries. They're texted."""
    application = await rider_applications.approve(session, await _get(session, application_id), admin)
    return _read(application, await session.get(User, application.user_id))


@router.post("/{application_id}/reject", response_model=RiderApplicationRead)
async def reject(application_id: uuid.UUID, data: RejectApplication, admin: AdminUser,
                 session: SessionDep):
    application = await rider_applications.reject(session, await _get(session, application_id),
                                                  admin, data.reason)
    return _read(application, await session.get(User, application.user_id))


@router.post("/{application_id}/check-id", response_model=RiderApplicationRead)
async def check_id(application_id: uuid.UUID, admin: AdminUser, session: SessionDep):
    """Run the ID checks again now (e.g. after funding the Dojah wallet, or a provider error)."""
    application = await _get(session, application_id)
    audit.record(session, admin, "rider_application.check_id", application)
    application = await id_verification.check(session, application)
    docs = await rider_applications.document_infos(session, [application.id])
    return _read(application, await session.get(User, application.user_id), docs.get(application.id))


@router.get("/{application_id}/documents/{document_id}")
async def view_document(application_id: uuid.UUID, document_id: uuid.UUID, admin: AdminUser,
                        session: SessionDep) -> Response:
    """The ID photo/PDF itself. Admins only, never cached, and every view is audited."""
    doc = await rider_applications.open_document(session, application_id, document_id, admin)
    ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "application/pdf": "pdf"}
    return Response(doc.data, media_type=doc.content_type, headers={
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
        "Content-Disposition": f'inline; filename="{doc.kind.value}.{ext.get(doc.content_type, "bin")}"',
    })
