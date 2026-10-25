"""The rider app's API. Each step only works in the right order (see delivery_service)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from sqlmodel import select

from app.api.deps import RiderUser, SessionDep
from app.core.config import settings
from app.core.exceptions import BadRequest
from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import Order, PaymentMethod, PaymentStatus
from app.schemas.delivery import (
    CodeSent,
    ConfirmAddress,
    OptionalReason,
    Position,
    PushSubscribe,
    PushUnsubscribe,
    Reason,
    RiderJob,
)
from app.services import delivery_service as svc
from app.services import events, push

router = APIRouter(prefix="/rider", tags=["RIDER"])
S = DeliveryStatus


def _job(delivery: Delivery, order: Order) -> RiderJob:
    accepted = delivery.status not in (S.ASSIGNED, S.UNASSIGNED)
    cash = (order.total if order.payment_method == PaymentMethod.COD
            and order.payment_status != PaymentStatus.PAID else None)
    return RiderJob(
        id=delivery.id, status=delivery.status.value, order_number=order.order_number,
        order_status=order.status.value, assigned_at=delivery.assigned_at,
        accept_deadline=delivery.accept_deadline if delivery.status == S.ASSIGNED else None,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone if accepted else None,
        delivery_address=order.delivery_address, landmark=delivery.address_landmark,
        notes=delivery.address_notes, dropoff_latitude=delivery.dropoff_latitude,
        dropoff_longitude=delivery.dropoff_longitude,
        address_confirmed=delivery.address_confirmed_at is not None,
        customer_changed_address=delivery.address_corrected_at is not None
        and delivery.address_confirmed_at is None and accepted,
        items=[{"name": i.product_name, "quantity": i.quantity} for i in order.items],
        total=order.total, payment_method=order.payment_method.value, collect_cash=cash,
        code_sent_at=delivery.code_sent_at,
        location_check_waived=delivery.geofence_override_at is not None,
    )


async def _respond(session, delivery: Delivery) -> RiderJob:
    await session.refresh(delivery)
    return _job(delivery, await session.get(Order, delivery.order_id, populate_existing=True))


@router.get("/deliveries", response_model=list[RiderJob])
async def my_deliveries(rider: RiderUser, session: SessionDep, active_only: bool = True):
    stmt = select(Delivery, Order).join(Order, Order.id == Delivery.order_id).where(
        Delivery.rider_id == rider.id)
    if active_only:
        stmt = stmt.where(Delivery.status.in_([S.ASSIGNED, S.ACCEPTED, S.EN_ROUTE, S.ARRIVED]))
    rows = (await session.exec(stmt.order_by(Delivery.assigned_at.desc()).limit(50))).all()
    return [_job(d, o) for d, o in rows]


@router.post("/deliveries/{delivery_id}/accept", response_model=RiderJob)
async def accept(delivery_id: uuid.UUID, rider: RiderUser, session: SessionDep):
    delivery = await svc.accept(session, await svc.rider_delivery(session, rider, delivery_id), rider)
    return await _respond(session, delivery)


@router.post("/deliveries/{delivery_id}/decline", status_code=204)
async def decline(delivery_id: uuid.UUID, rider: RiderUser, session: SessionDep,
                  data: OptionalReason | None = None):
    await svc.decline(session, await svc.rider_delivery(session, rider, delivery_id), rider,
                      data.reason if data else None)


@router.post("/deliveries/{delivery_id}/confirm-address", response_model=RiderJob)
async def confirm_address(delivery_id: uuid.UUID, data: ConfirmAddress, rider: RiderUser,
                          session: SessionDep):
    """Before setting off: call the customer, check the address and landmark, and drop the pin
    on the exact spot (the delivery code only works near this pin)."""
    delivery = await svc.confirm_address(
        session, await svc.rider_delivery(session, rider, delivery_id), rider,
        latitude=data.latitude, longitude=data.longitude, landmark=data.landmark, notes=data.notes)
    return await _respond(session, delivery)


@router.post("/deliveries/{delivery_id}/start", response_model=RiderJob)
async def start(delivery_id: uuid.UUID, rider: RiderUser, session: SessionDep):
    delivery = await svc.start(session, await svc.rider_delivery(session, rider, delivery_id), rider)
    return await _respond(session, delivery)


@router.post("/location", status_code=204)
async def location(data: Position, rider: RiderUser, session: SessionDep):
    """GPS ping (the app sends one every ~15 s while a delivery is active)."""
    await svc.record_location(session, rider, data.latitude, data.longitude)


@router.post("/deliveries/{delivery_id}/arrive", response_model=RiderJob)
async def arrive(delivery_id: uuid.UUID, data: Position, rider: RiderUser, session: SessionDep):
    delivery = await svc.arrive(session, await svc.rider_delivery(session, rider, delivery_id), rider,
                                data.latitude, data.longitude)
    return await _respond(session, delivery)


@router.post("/deliveries/{delivery_id}/send-code", response_model=CodeSent)
async def send_code(delivery_id: uuid.UUID, data: Position, rider: RiderUser, session: SessionDep):
    """Texts a one-time code to the CUSTOMER. The code is never shown to the rider."""
    return await svc.send_code(session, await svc.rider_delivery(session, rider, delivery_id), rider,
                               data.latitude, data.longitude)


@router.post("/deliveries/{delivery_id}/complete", response_model=RiderJob)
async def complete(
    delivery_id: uuid.UUID, rider: RiderUser, session: SessionDep,
    code: Annotated[str, Form(min_length=6, max_length=6, description="The code the customer read out")],
    latitude: Annotated[float, Form(ge=-90, le=90)],
    longitude: Annotated[float, Form(ge=-180, le=180)],
    photo: Annotated[UploadFile, File(description="Photo of the handover (JPEG/PNG/WebP)")],
):
    data = await photo.read(settings.MAX_UPLOAD_BYTES + 1)
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise BadRequest("The photo is too big", code="file_too_large")
    delivery = await svc.complete(session, await svc.rider_delivery(session, rider, delivery_id), rider,
                                  code=code, latitude=latitude, longitude=longitude, photo=data)
    return await _respond(session, delivery)


@router.post("/deliveries/{delivery_id}/fail", response_model=RiderJob)
async def fail(delivery_id: uuid.UUID, data: Reason, rider: RiderUser, session: SessionDep):
    """Can't deliver (customer unreachable, refused, ...). The admin decides what happens next."""
    delivery = await svc.fail(session, await svc.rider_delivery(session, rider, delivery_id), rider,
                              data.reason)
    return await _respond(session, delivery)


@router.get("/events")
async def rider_events(request: Request, rider: RiderUser,
                       last_event_id: Annotated[str | None, Header()] = None):
    """Live events for this rider (server-sent events): new offers, cancellations,
    customer address changes. The app chimes on them."""
    return events.response(request, events.rider_stream(rider.id), last_event_id)


# ---------------------------------------------------------------- push alerts
@router.get("/push/key")
async def push_key(_: RiderUser) -> dict:
    """The server's public VAPID key, for pushManager.subscribe(). `enabled` is false when
    push isn't configured (the app then hides the "turn on alerts" button)."""
    return {"enabled": push.enabled(), "public_key": settings.VAPID_PUBLIC_KEY if push.enabled() else None}


@router.post("/push/subscribe", status_code=201)
async def push_subscribe(data: PushSubscribe, rider: RiderUser, session: SessionDep,
                         user_agent: Annotated[str | None, Header()] = None) -> dict:
    """Save this phone so new offers can alert the rider even when the app is closed."""
    await push.subscribe(session, rider, endpoint=data.endpoint, p256dh=data.keys.p256dh,
                         auth=data.keys.auth, user_agent=user_agent)
    return {"subscribed": True}


@router.post("/push/unsubscribe", status_code=204)
async def push_unsubscribe(data: PushUnsubscribe, rider: RiderUser, session: SessionDep):
    await push.unsubscribe(session, rider, data.endpoint)
