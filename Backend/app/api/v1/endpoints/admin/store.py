import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import AdminUser, SessionDep
from app.core.exceptions import BadRequest, Conflict, NotFound
from app.models.audit_log import AuditLog
from app.models.coupon import Coupon
from app.models.delivery import ACTIVE_STATUSES, Delivery
from app.models.delivery_zone import DeliveryZone
from app.models.rider_application import ApplicationStatus, RiderApplication
from app.models.user import User, UserRole
from app.schemas.admin import (
    AdminUserCreate,
    AuditLogRead,
    CouponCreate,
    CouponRead,
    CouponUpdate,
    UserAdminUpdate,
)
from app.schemas.auth import UserRead
from app.schemas.catalog import ZoneCreate, ZoneRead, ZoneUpdate
from app.services import audit, auth_service
from app.utils.pagination import Page, PageParams

router = APIRouter(prefix="/admin", tags=["ADMIN: STORE SETTINGS"])


# ----------------------------------- zones ------------------------------------
@router.get("/zones", response_model=list[ZoneRead])
async def list_zones(_: AdminUser, session: SessionDep):
    return (await session.exec(select(DeliveryZone).order_by(DeliveryZone.name))).all()


@router.post("/zones", response_model=ZoneRead, status_code=status.HTTP_201_CREATED)
async def create_zone(data: ZoneCreate, admin: AdminUser, session: SessionDep):
    if (await session.exec(select(DeliveryZone.id).where(DeliveryZone.name == data.name))).first():
        raise Conflict("A delivery area with this name already exists")
    zone = DeliveryZone(**data.model_dump())
    session.add(zone)
    audit.record(session, admin, "zone.create", zone, changes=audit.snapshot(zone))
    await session.commit()
    await session.refresh(zone)
    return zone


@router.patch("/zones/{zone_id}", response_model=ZoneRead)
async def update_zone(zone_id: uuid.UUID, data: ZoneUpdate, admin: AdminUser, session: SessionDep):
    zone = await session.get(DeliveryZone, zone_id)
    if not zone:
        raise NotFound("Zone not found")
    changes = data.model_dump(exclude_unset=True)
    if changes.get("name") and changes["name"] != zone.name and (await session.exec(
            select(DeliveryZone.id).where(DeliveryZone.name == changes["name"]))).first():
        raise Conflict("A delivery area with this name already exists")
    before = audit.snapshot(zone, list(changes))
    for k, v in changes.items():
        setattr(zone, k, v)
    session.add(zone)
    audit.record(session, admin, "zone.update", zone, changes=audit.diff(before, zone))
    await session.commit()
    await session.refresh(zone)
    return zone


# ---------------------------------- coupons -----------------------------------
@router.get("/coupons", response_model=list[CouponRead])
async def list_coupons(_: AdminUser, session: SessionDep):
    return (await session.exec(select(Coupon).order_by(Coupon.created_at.desc()))).all()


@router.post("/coupons", response_model=CouponRead, status_code=status.HTTP_201_CREATED)
async def create_coupon(data: CouponCreate, admin: AdminUser, session: SessionDep):
    if (await session.exec(select(Coupon.id).where(Coupon.code == data.code))).first():
        raise Conflict("This coupon code already exists", code="coupon_exists")
    coupon = Coupon(**data.model_dump())
    session.add(coupon)
    audit.record(session, admin, "coupon.create", coupon, changes=audit.snapshot(coupon))
    await session.commit()
    await session.refresh(coupon)
    return coupon


@router.patch("/coupons/{coupon_id}", response_model=CouponRead)
async def update_coupon(coupon_id: uuid.UUID, data: CouponUpdate, admin: AdminUser, session: SessionDep):
    coupon = await session.get(Coupon, coupon_id)
    if not coupon:
        raise NotFound("Coupon not found")
    changes = data.model_dump(exclude_unset=True)
    before = audit.snapshot(coupon, list(changes))
    for k, v in changes.items():
        setattr(coupon, k, v)
    session.add(coupon)
    audit.record(session, admin, "coupon.update", coupon, changes=audit.diff(before, coupon))
    await session.commit()
    await session.refresh(coupon)
    return coupon


# ----------------------------------- users ------------------------------------
@router.get("/users", response_model=Page[UserRead])
async def list_users(
    _: AdminUser, session: SessionDep, params: Annotated[PageParams, Depends()],
    role: UserRole | None = None, q: str | None = None,
):
    conds = []
    if role:
        conds.append(User.role == role)
    if q:
        like = f"%{q}%"
        conds.append(User.email.ilike(like) | User.full_name.ilike(like) | User.phone.ilike(like))
    total = (await session.exec(select(func.count()).select_from(User).where(*conds))).one()
    rows = (await session.exec(select(User).where(*conds).order_by(User.created_at.desc())
                               .offset(params.offset).limit(params.size))).all()
    return Page[UserRead].build([UserRead.model_validate(u) for u in rows], total, params)


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(data: AdminUserCreate, admin: AdminUser, session: SessionDep):
    """Create a staff account (admin by default, or rider). This is the only way to make
    a new admin: public /auth/register always creates customers."""
    user = await auth_service.register(session, data, role=data.role)
    audit.record(session, admin, "user.create", user,
                 changes={"email": user.email, "role": user.role.value})
    await session.commit()
    return user


@router.get("/riders")
async def list_riders(_: AdminUser, session: SessionDep) -> list[dict]:
    """Working and suspended riders. Applications still being decided are on the board."""
    rows = (await session.exec(
        select(User, RiderApplication).join(RiderApplication, RiderApplication.user_id == User.id, isouter=True)
        .where(User.role == UserRole.RIDER).order_by(User.full_name))).all()
    busy = (await session.exec(select(Delivery.rider_id, func.count()).where(
        Delivery.status.in_(ACTIVE_STATUSES)).group_by(Delivery.rider_id))).all()
    active = dict(busy)
    return [{"id": u.id, "full_name": u.full_name, "email": u.email, "phone": u.phone, "is_active": u.is_active,
             "vehicle_type": a.vehicle_type.value if a else None, "area": a.area if a else None,
             "active_deliveries": active.get(u.id, 0)}
            for u, a in rows if not a or a.status == ApplicationStatus.APPROVED]


@router.patch("/users/{user_id}", response_model=UserRead)
async def update_user(user_id: uuid.UUID, data: UserAdminUpdate, admin: AdminUser, session: SessionDep):
    """Make someone a rider/admin, or disable an account."""
    user = await session.get(User, user_id)
    if not user:
        raise NotFound("User not found")
    if user.id == admin.id:
        raise BadRequest("You cannot change your own role or active status")
    changes = data.model_dump(exclude_unset=True)
    if user.role == UserRole.RIDER and changes.get("is_active") is False and (await session.exec(
            select(Delivery.id).where(Delivery.rider_id == user.id, Delivery.status.in_(ACTIVE_STATUSES)))).first():
        raise Conflict("This rider has a delivery in progress. Change its rider first.", code="rider_busy")
    if changes.get("is_active") is True and user.role == UserRole.RIDER:
        application = (await session.exec(select(RiderApplication).where(RiderApplication.user_id == user.id))).first()
        if application and application.status != ApplicationStatus.APPROVED:
            raise Conflict("This rider's application hasn't been approved", code="application_not_approved")
    before = audit.snapshot(user, list(changes))
    for k, v in changes.items():
        setattr(user, k, v)
    session.add(user)
    audit.record(session, admin, "user.update", user, changes=audit.diff(before, user))
    await session.commit()
    await session.refresh(user)
    return user


# --------------------------------- audit log ----------------------------------
@router.get("/audit-logs", response_model=Page[AuditLogRead])
async def list_audit_logs(
    _: AdminUser, session: SessionDep, params: Annotated[PageParams, Depends()],
    entity_type: str | None = None, entity_id: str | None = None,
    actor_id: uuid.UUID | None = None,
):
    """Who changed what in the admin panel, newest first."""
    conds = []
    if entity_type:
        conds.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conds.append(AuditLog.entity_id == entity_id)
    if actor_id:
        conds.append(AuditLog.actor_id == actor_id)
    total = (await session.exec(select(func.count()).select_from(AuditLog).where(*conds))).one()
    rows = (await session.exec(select(AuditLog).where(*conds).order_by(AuditLog.created_at.desc())
                               .offset(params.offset).limit(params.size))).all()
    return Page[AuditLogRead].build([AuditLogRead.model_validate(r) for r in rows], total, params)
