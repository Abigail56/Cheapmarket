import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Request
from sqlmodel import select

from app.api.deps import AdminUser, SessionDep
from app.core.exceptions import NotFound
from app.models.delivery import ACTIVE_STATUSES, Delivery, DeliveryStatus
from app.models.order import Order, OrderStatus
from app.models.rider_application import ApplicationStatus, RiderApplication
from app.models.user import User, UserRole
from app.schemas.admin import DeliveryRead
from app.schemas.delivery import Reason
from app.services import delivery_service, events, rider_applications

router = APIRouter(prefix="/admin", tags=["ADMIN DELIVERIES"])


@router.get("/deliveries/board")
async def board(_: AdminUser, session: SessionDep) -> dict:
    """Everything the live dashboard needs in one call: orders waiting for a rider,
    deliveries in progress (with the rider's last position) and the riders."""
    waiting_orders = (await session.exec(
        select(Order).where(Order.status.in_([OrderStatus.CONFIRMED, OrderStatus.PACKED,
                                              OrderStatus.OUT_FOR_DELIVERY]))
        .order_by(Order.created_at))).all()
    deliveries = {d.order_id: d for d in (await session.exec(select(Delivery).where(
        Delivery.order_id.in_([o.id for o in waiting_orders])))).all()} if waiting_orders else {}
    new_orders = (await session.exec(
        select(Order).where(Order.status == OrderStatus.PENDING).order_by(Order.created_at))).all()
    delivered = (await session.exec(
        select(Delivery, Order, User).join(Order, Order.id == Delivery.order_id)
        .join(User, User.id == Delivery.rider_id, isouter=True)
        .where(Delivery.status == DeliveryStatus.DELIVERED)
        .order_by(Delivery.delivered_at.desc()).limit(8))).all()
    needs_rider = [
        {"order_number": o.order_number, "customer_name": o.customer_name, "total": float(o.total),
         "payment_method": o.payment_method.value, "placed_at": o.created_at,
         "delivery_address": o.delivery_address,
         "failure_reason": deliveries[o.id].failure_reason if o.id in deliveries else None}
        for o in waiting_orders
        if (o.id in deliveries and deliveries[o.id].status in delivery_service.NEEDS_NEW_RIDER)
        or (o.id not in deliveries and o.status != OrderStatus.OUT_FOR_DELIVERY)
    ]
    active = (await session.exec(
        select(Delivery, Order, User).join(Order, Order.id == Delivery.order_id)
        .join(User, User.id == Delivery.rider_id)
        .where(Delivery.status.in_(ACTIVE_STATUSES)).order_by(Delivery.assigned_at))).all()
    riders = (await session.exec(select(User).where(User.role == UserRole.RIDER,
                                                    User.is_active.is_(True))
                                 .order_by(User.full_name))).all()
    busy = {d.rider_id for d, _, _ in active}
    applications = (await session.exec(
        select(RiderApplication, User).join(User, User.id == RiderApplication.user_id)
        .where(RiderApplication.status == ApplicationStatus.PENDING)
        .order_by(RiderApplication.created_at).limit(50))).all()
    docs = await rider_applications.document_infos(session, [a.id for a, _ in applications])
    return {
        "applications": [{"id": str(a.id), "full_name": u.full_name, "phone": u.phone, "email": u.email,
                          "vehicle_type": a.vehicle_type.value, "plate_number": a.plate_number,
                          "id_type": a.id_type.value if a.id_type else None, "id_number": a.id_number,
                          "area": a.area, "note": a.note, "applied_at": a.created_at,
                          "id_check_status": a.id_check_status.value, "id_check_reasons": a.id_check_reasons or [],
                          "id_record_name": a.id_record_name, "id_name_match": a.id_name_match,
                          "id_face_match": a.id_face_match,
                          "documents": [{"id": str(d["id"]), "kind": d["kind"].value,
                                         "content_type": d["content_type"]} for d in docs.get(a.id, [])]}
                         for a, u in applications],
        "new_orders": [{"order_number": o.order_number, "customer_name": o.customer_name,
                        "total": float(o.total), "payment_method": o.payment_method.value,
                        "payment_status": o.payment_status.value, "placed_at": o.created_at,
                        "delivery_address": o.delivery_address} for o in new_orders],
        "delivered": [{"order_number": o.order_number, "customer_name": o.customer_name,
                       "rider_name": r.full_name if r else None, "delivered_at": d.delivered_at,
                       "proof_photo_url": d.proof_photo_url} for d, o, r in delivered],
        "needs_rider": needs_rider,
        "active": [{"delivery": DeliveryRead.model_validate(d).model_dump(mode="json"),
                    "order_number": o.order_number, "customer_name": o.customer_name,
                    "customer_phone": o.customer_phone,
                    "delivery_address": o.delivery_address, "rider_name": r.full_name,
                    "rider_phone": r.phone} for d, o, r in active],
        "riders": [{"id": str(r.id), "name": r.full_name, "phone": r.phone, "busy": r.id in busy}
                   for r in riders],
    }


@router.post("/deliveries/{delivery_id}/override-location", response_model=DeliveryRead)
async def override_location(delivery_id: uuid.UUID, data: Reason, admin: AdminUser,
                            session: SessionDep):
    """When the rider is really at the door but GPS disagrees: lets them send the code and
    finish without the distance check. Audited with your reason."""
    delivery = await session.get(Delivery, delivery_id, with_for_update=True)
    if not delivery:
        raise NotFound("Delivery not found")
    return await delivery_service.override_geofence(session, delivery, admin, data.reason)


@router.get("/events")
async def admin_events(request: Request, _: AdminUser,
                       last_event_id: Annotated[str | None, Header()] = None):
    """Live events for the dashboard (server-sent events): new orders, rider accepted /
    declined / no answer, rider positions, wrong delivery codes, deliveries."""
    return events.response(request, events.ADMIN, last_event_id)
