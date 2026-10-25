"""The delivery journey, from the admin assigning a rider to the code-verified handover.

    assigned --accept--> accepted --confirm address--> --start--> en_route --arrive--> arrived
       |                                                                               |
    decline / no answer in RIDER_ACCEPT_SECONDS                     send code, then photo + code
       v                                                                               v
    unassigned (admin reassigns)                                                   delivered

Every step checks who is asking and what state the delivery is in, so the rider app
can't skip ahead. The order's own status follows along (out_for_delivery, delivered).

Why the delivery code can't be faked:
  * the server makes it (6 random digits) and texts it ONLY to the customer's phone;
    no API ever returns it, the rider's app included
  * only an HMAC of it is stored, bound to this one delivery: a code from another order,
    or a guess, never matches
  * it expires after DELIVERY_CODE_TTL_SECONDS and dies after DELIVERY_CODE_MAX_ATTEMPTS
    wrong tries (each wrong try alerts the admin)
  * sending and using it both require the rider's GPS to be within GEOFENCE_METERS of
    the confirmed pin (an admin can override, which is audited), plus a photo
"""
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequest, Conflict, NotFound
from app.models.delivery import Delivery, DeliveryStatus
from app.models.order import Order, OrderStatus, OrderStatusHistory
from app.models.user import User, UserRole
from app.services import audit, events, notifications, order_service, storage
from app.services.geo import distance_m, eta_minutes

S = DeliveryStatus
CAN_EDIT_ADDRESS = (S.UNASSIGNED, S.ASSIGNED, S.ACCEPTED)


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=UTC) if moment and moment.tzinfo is None else moment


def _code_hash(delivery: Delivery, code: str) -> str:
    msg = f"delivery:{delivery.id}:{code}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), msg, hashlib.sha256).hexdigest()


async def _event(delivery: Delivery, event: str, **extra) -> None:
    data = {"delivery_id": delivery.id, "order_id": delivery.order_id, "status": delivery.status.value,
            **extra}
    streams = [events.ADMIN, events.track_stream(delivery.order_id)]
    if delivery.rider_id:
        streams.append(events.rider_stream(delivery.rider_id))
    await events.publish(streams, event, data)


def _require(delivery: Delivery, *allowed: DeliveryStatus, action: str) -> None:
    if delivery.status not in allowed:
        raise Conflict(f"You can't {action} while the delivery is {delivery.status.value}",
                       code="wrong_delivery_state")


def _check_near(delivery: Delivery, lat: float, lng: float) -> None:
    if delivery.geofence_override_at:
        return
    if delivery.dropoff_latitude is None or delivery.dropoff_longitude is None:
        raise BadRequest("Confirm the customer's address pin first", code="no_pin")
    gap = distance_m((lat, lng), (delivery.dropoff_latitude, delivery.dropoff_longitude))
    if gap > settings.GEOFENCE_METERS:
        raise BadRequest(
            f"You are about {round(gap)} m from the customer's pin. Get within "
            f"{settings.GEOFENCE_METERS} m, or ask the admin to override if GPS is wrong.",
            code="too_far",
        )


def _remember_position(delivery: Delivery, lat: float, lng: float) -> None:
    delivery.last_latitude, delivery.last_longitude, delivery.last_location_at = lat, lng, _now()


async def rider_delivery(session: AsyncSession, rider: User, delivery_id, *, lock: bool = True) -> Delivery:
    """The rider's own delivery, row-locked so two taps can't race each other."""
    delivery = await session.get(Delivery, delivery_id, with_for_update=lock,
                                 populate_existing=True)
    if not delivery or delivery.rider_id != rider.id:
        raise NotFound("Delivery not found")
    return delivery


async def _order(session: AsyncSession, delivery: Delivery) -> Order:
    return await session.get(Order, delivery.order_id)


async def delivery_for_order(session: AsyncSession, order: Order, *, lock: bool = False) -> Delivery | None:
    stmt = select(Delivery).where(Delivery.order_id == order.id)
    if lock:
        stmt = stmt.with_for_update()
    return (await session.exec(stmt.execution_options(populate_existing=True))).first()


# ------------------------------------ admin -----------------------------------
async def assign(session: AsyncSession, order: Order, rider: User, admin: User) -> Delivery:
    if order.status not in (OrderStatus.CONFIRMED, OrderStatus.PACKED):
        raise BadRequest("Riders can only be assigned to confirmed or packed orders")
    if rider.role != UserRole.RIDER or not rider.is_active:
        raise BadRequest("That user is not an active rider")
    delivery = await delivery_for_order(session, order, lock=True)
    previous_rider = delivery.rider_id if delivery else None
    if delivery and delivery.status in (S.EN_ROUTE, S.ARRIVED, S.DELIVERED):
        raise Conflict("This delivery is already on the road", code="wrong_delivery_state")
    if delivery is None:
        delivery = Delivery(order_id=order.id)
    delivery.rider_id = rider.id
    delivery.status = S.ASSIGNED
    delivery.assigned_at = _now()
    delivery.accept_deadline = _now() + timedelta(seconds=settings.RIDER_ACCEPT_SECONDS)
    delivery.accepted_at = None
    delivery.address_confirmed_at = None  # the new rider confirms for themselves
    session.add(delivery)
    session.add(OrderStatusHistory(order_id=order.id, status=order.status, changed_by=admin.id,
                                   note=f"Assigned to rider {rider.full_name}"))
    audit.record(session, admin, "order.assign_rider", order, entity_id=order.order_number,
                 changes={"rider_id": str(rider.id)})
    await session.commit()

    if previous_rider and previous_rider != rider.id:
        await events.publish([events.rider_stream(previous_rider)], "delivery.unassigned",
                             {"delivery_id": delivery.id, "order_id": order.id})
    await _event(delivery, "delivery.assigned", order_number=order.order_number,
                 rider_name=rider.full_name, accept_deadline=delivery.accept_deadline)
    minutes = settings.RIDER_ACCEPT_SECONDS // 60
    await notifications.push_rider(rider.id, f"New delivery: {order.order_number}",
                                   f"Accept within {minutes} minutes. Tap to open.",
                                   tag=f"offer-{delivery.id}")
    if rider.phone:
        await notifications.enqueue("sms", rider.phone,
                                    f"Cheapmarketdeal: new delivery {order.order_number}. Open the "
                                    f"rider app and accept within {minutes} minutes.")
    return delivery


async def override_geofence(session: AsyncSession, delivery: Delivery, admin: User, reason: str) -> Delivery:
    _require(delivery, S.ACCEPTED, S.EN_ROUTE, S.ARRIVED, action="override the location check")
    delivery.geofence_override_at = _now()
    delivery.geofence_override_by = admin.id
    delivery.geofence_override_reason = reason
    session.add(delivery)
    audit.record(session, admin, "delivery.geofence_override", delivery, changes={"reason": reason})
    await session.commit()
    await _event(delivery, "delivery.geofence_overridden", reason=reason)
    return delivery


async def expire_unaccepted(session: AsyncSession) -> int:
    """Worker job: assignments nobody accepted in time go back to the admin."""
    rows = (await session.exec(select(Delivery).where(
        Delivery.status == S.ASSIGNED, Delivery.accept_deadline < _now(),
    ).with_for_update(skip_locked=True))).all()
    expired = []
    for delivery in rows:
        order = await _order(session, delivery)
        expired.append((delivery, delivery.rider_id))
        delivery.status, delivery.rider_id = S.UNASSIGNED, None
        session.add(delivery)
        session.add(OrderStatusHistory(order_id=order.id, status=order.status,
                                       note="Rider did not accept in time; needs a new rider"))
    if expired:
        await session.commit()
    for delivery, rider_id in expired:
        await events.publish([events.ADMIN, events.rider_stream(rider_id)], "delivery.expired",
                             {"delivery_id": delivery.id, "order_id": delivery.order_id,
                              "status": delivery.status.value})
    return len(expired)


# ------------------------------------ rider -----------------------------------
async def accept(session: AsyncSession, delivery: Delivery, rider: User) -> Delivery:
    _require(delivery, S.ASSIGNED, action="accept")
    if _aware(delivery.accept_deadline) and _aware(delivery.accept_deadline) < _now():
        raise Conflict("Too late: this delivery was offered to you for "
                       f"{settings.RIDER_ACCEPT_SECONDS // 60} minutes", code="offer_expired")
    delivery.status, delivery.accepted_at = S.ACCEPTED, _now()
    session.add(delivery)
    order = await _order(session, delivery)
    session.add(OrderStatusHistory(order_id=order.id, status=order.status, changed_by=rider.id,
                                   note=f"Rider {rider.full_name} accepted"))
    await session.commit()
    await _event(delivery, "delivery.accepted", rider_name=rider.full_name)
    await notifications.order_event(order, "rider_accepted", rider=rider.full_name.split()[0])
    return delivery


async def decline(session: AsyncSession, delivery: Delivery, rider: User, reason: str | None) -> Delivery:
    _require(delivery, S.ASSIGNED, S.ACCEPTED, action="decline")
    order = await _order(session, delivery)
    delivery.status, delivery.rider_id = S.UNASSIGNED, None
    session.add(delivery)
    session.add(OrderStatusHistory(order_id=order.id, status=order.status, changed_by=rider.id,
                                   note=f"Rider {rider.full_name} declined" + (f": {reason}" if reason else "")))
    await session.commit()
    await events.publish([events.ADMIN, events.rider_stream(rider.id)], "delivery.declined",
                         {"delivery_id": delivery.id, "order_id": order.id, "status": delivery.status.value,
                          "order_number": order.order_number, "rider_name": rider.full_name,
                          "reason": reason})
    return delivery


async def confirm_address(session: AsyncSession, delivery: Delivery, rider: User, *, latitude: float,
                          longitude: float, landmark: str | None, notes: str | None) -> Delivery:
    """The rider checks the address with the customer (usually by phone) and pins it."""
    _require(delivery, S.ACCEPTED, action="confirm the address")
    delivery.dropoff_latitude, delivery.dropoff_longitude = latitude, longitude
    if landmark is not None:
        delivery.address_landmark = landmark
    if notes is not None:
        delivery.address_notes = notes
    delivery.address_confirmed_at = _now()
    session.add(delivery)
    await session.commit()
    await _event(delivery, "delivery.address_confirmed")
    return delivery


async def start(session: AsyncSession, delivery: Delivery, rider: User) -> Delivery:
    _require(delivery, S.ACCEPTED, action="start the journey")
    if not delivery.address_confirmed_at:
        raise BadRequest("Confirm the customer's address before you start", code="address_not_confirmed")
    order = await _order(session, delivery)
    delivery.status, delivery.started_at = S.EN_ROUTE, _now()
    session.add(delivery)
    # the order follows: confirmed -> packed -> out_for_delivery (these commit, and text the customer)
    if order.status == OrderStatus.CONFIRMED:
        await order_service.change_status(session, order, OrderStatus.PACKED, rider, "Packed")
    await order_service.change_status(session, order, OrderStatus.OUT_FOR_DELIVERY, rider,
                                      "Rider started the journey")
    await _event(delivery, "delivery.started")
    return delivery


async def record_location(session: AsyncSession, rider: User, latitude: float, longitude: float) -> int:
    """GPS ping from the rider app. Kept on the rider's active deliveries, and passed live to
    the admin map and (only while on the way) to the customer's tracking page."""
    rows = (await session.exec(select(Delivery).where(
        Delivery.rider_id == rider.id, Delivery.status.in_([S.ACCEPTED, S.EN_ROUTE, S.ARRIVED])))).all()
    for delivery in rows:
        _remember_position(delivery, latitude, longitude)
        session.add(delivery)
    if rows:
        await session.commit()
    for delivery in rows:
        streams = [events.ADMIN]
        if delivery.status in (S.EN_ROUTE, S.ARRIVED):
            streams.append(events.track_stream(delivery.order_id))
        data = {"delivery_id": delivery.id, "order_id": delivery.order_id, "rider_id": rider.id,
                "latitude": latitude, "longitude": longitude, "status": delivery.status.value}
        if delivery.status == S.EN_ROUTE and delivery.dropoff_latitude is not None:
            data["eta_minutes"] = eta_minutes((latitude, longitude),
                                              (delivery.dropoff_latitude, delivery.dropoff_longitude))
        await events.publish(streams, "rider.location", data)
    return len(rows)


async def arrive(session: AsyncSession, delivery: Delivery, rider: User, latitude: float, longitude: float) -> Delivery:
    _require(delivery, S.EN_ROUTE, action="mark yourself arrived")
    _check_near(delivery, latitude, longitude)
    _remember_position(delivery, latitude, longitude)
    delivery.status, delivery.arrived_at = S.ARRIVED, _now()
    session.add(delivery)
    await session.commit()
    await _event(delivery, "delivery.arrived")
    await notifications.order_event(await _order(session, delivery), "rider_arrived")
    return delivery


async def send_code(session: AsyncSession, delivery: Delivery, rider: User, latitude: float, longitude: float) -> dict:
    _require(delivery, S.ARRIVED, action="send the delivery code")
    _check_near(delivery, latitude, longitude)
    sent = _aware(delivery.code_sent_at)
    if sent and (_now() - sent).total_seconds() < settings.DELIVERY_CODE_RESEND_SECONDS:
        wait = settings.DELIVERY_CODE_RESEND_SECONDS - int((_now() - sent).total_seconds())
        raise BadRequest(f"A code was just sent. You can resend in {wait} seconds.", code="code_recently_sent")
    code = f"{secrets.randbelow(10**6):06d}"
    delivery.code_hash = _code_hash(delivery, code)  # a new code replaces the old one
    delivery.code_expires_at = _now() + timedelta(seconds=settings.DELIVERY_CODE_TTL_SECONDS)
    delivery.code_attempts = 0
    delivery.code_sent_at = _now()
    _remember_position(delivery, latitude, longitude)
    session.add(delivery)
    await session.commit()
    order = await _order(session, delivery)
    minutes = settings.DELIVERY_CODE_TTL_SECONDS // 60
    text = (f"Cheapmarketdeal: your delivery code for order {order.order_number} is {code}. "
            f"Give it to the rider ONLY when you have your items. Valid for {minutes} minutes.")
    await notifications.enqueue("sms", order.customer_phone, text)
    if order.customer_email:
        await notifications.enqueue("email", order.customer_email, text,
                                    subject=f"Delivery code for {order.order_number}")
    await _event(delivery, "delivery.code_sent")  # the code itself is never in an event
    return {"sent": True, "expires_in_minutes": minutes}


async def complete(session: AsyncSession, delivery: Delivery, rider: User, *, code: str,
                   latitude: float, longitude: float, photo: bytes) -> Delivery:
    _require(delivery, S.ARRIVED, action="complete the delivery")
    _check_near(delivery, latitude, longitude)
    if not delivery.code_hash:
        raise BadRequest("Send the customer a delivery code first", code="no_code")
    if _aware(delivery.code_expires_at) < _now():
        raise BadRequest("The code has expired. Send a new one.", code="code_expired")
    if delivery.code_attempts >= settings.DELIVERY_CODE_MAX_ATTEMPTS:
        raise BadRequest("Too many wrong codes. Send a new one.", code="code_locked")
    if not hmac.compare_digest(delivery.code_hash, _code_hash(delivery, code.strip())):
        delivery.code_attempts += 1
        left = settings.DELIVERY_CODE_MAX_ATTEMPTS - delivery.code_attempts
        session.add(delivery)
        await session.commit()
        await _event(delivery, "delivery.code_wrong", attempts=delivery.code_attempts)
        raise BadRequest(f"That code is not right. {left} tries left." if left else
                         "That code is not right. Send the customer a new code.", code="wrong_code")

    photo_url = await storage.save_image(photo, "proof")  # checks it's a real JPEG/PNG/WebP
    order = await _order(session, delivery)
    delivery.status, delivery.delivered_at = S.DELIVERED, _now()
    delivery.code_hash = None  # used: nothing left to replay
    delivery.proof_photo_url = photo_url
    delivery.delivered_latitude, delivery.delivered_longitude = latitude, longitude
    _remember_position(delivery, latitude, longitude)
    session.add(delivery)
    # commits the delivery too; marks COD paid and texts the customer
    await order_service.change_status(session, order, OrderStatus.DELIVERED, rider,
                                      "Delivered: code verified, photo taken")
    await _event(delivery, "delivery.delivered", order_number=order.order_number,
                 rider_name=rider.full_name)
    return delivery


async def fail(session: AsyncSession, delivery: Delivery, rider: User, reason: str) -> Delivery:
    _require(delivery, S.EN_ROUTE, S.ARRIVED, action="report a failed delivery")
    order = await _order(session, delivery)
    delivery.status, delivery.failure_reason = S.FAILED, reason
    delivery.code_hash = None
    session.add(delivery)
    session.add(OrderStatusHistory(order_id=order.id, status=order.status, changed_by=rider.id,
                                   note=f"Delivery failed: {reason}"))
    await session.commit()
    await _event(delivery, "delivery.failed", reason=reason, order_number=order.order_number)
    return delivery


# ---------------------------------- customer ----------------------------------
async def order_by_token(session: AsyncSession, token: str) -> Order:
    order = (await session.exec(select(Order).where(Order.tracking_token == token))).first()
    if not order:
        raise NotFound("Tracking link not found")
    return order


async def customer_correct_address(session: AsyncSession, order: Order, *, latitude: float | None,
                                   longitude: float | None, landmark: str | None, notes: str | None) -> Delivery:
    """From the tracking link, until the rider sets off. If the rider had already confirmed,
    they must confirm again (and their app chimes)."""
    if order.status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        raise Conflict("This order is finished", code="order_closed")
    delivery = await delivery_for_order(session, order, lock=True)
    if delivery and delivery.status not in CAN_EDIT_ADDRESS:
        raise Conflict("The rider is already on the way. Call them to change the address.",
                       code="rider_on_the_way")
    if delivery is None:  # no rider yet: keep the correction ready for whoever gets assigned
        delivery = Delivery(order_id=order.id, status=S.UNASSIGNED)
    if (latitude is None) != (longitude is None):
        raise BadRequest("Send both latitude and longitude")
    if latitude is not None:
        delivery.dropoff_latitude, delivery.dropoff_longitude = latitude, longitude
    if landmark is not None:
        delivery.address_landmark = landmark
    if notes is not None:
        delivery.address_notes = notes
    reconfirm = delivery.address_confirmed_at is not None
    delivery.address_confirmed_at = None
    delivery.address_corrected_at = _now()
    session.add(delivery)
    await session.commit()
    await _event(delivery, "delivery.address_corrected", rider_must_reconfirm=reconfirm)
    if delivery.rider_id and delivery.status in (S.ASSIGNED, S.ACCEPTED):
        await notifications.push_rider(delivery.rider_id, f"Address changed: {order.order_number}",
                                       "The customer updated the delivery address. Check it and "
                                       "confirm again before you set off.",
                                       tag=f"address-{delivery.id}")
    return delivery


def _timeline(history: list[OrderStatusHistory]) -> list[dict]:
    """One line per status the order reached (internal notes are not shown to customers)."""
    steps, last = [], None
    for h in history:
        if h.status != last:
            steps.append({"status": h.status.value, "at": h.created_at})
            last = h.status
    return steps


def tracking_view(order: Order, delivery: Delivery | None, history: list[OrderStatusHistory],
                  rider: User | None) -> dict:
    """What the customer sees. The rider's position only while on the way and fresh,
    the rider's first name only, and never anything about the delivery code."""
    view = {
        "order_number": order.order_number,
        "status": order.status.value,
        "placed_at": order.created_at,
        "items": [{"name": i.product_name, "quantity": i.quantity} for i in order.items],
        "total": order.total,
        "payment_method": order.payment_method.value,
        "payment_status": order.payment_status.value,
        "delivery_address": order.delivery_address,
        "timeline": _timeline(history),
        "can_edit_address": (order.status not in (OrderStatus.DELIVERED, OrderStatus.CANCELLED)
                             and (delivery is None or delivery.status in CAN_EDIT_ADDRESS)),
        "delivery": None,
    }
    if delivery is None:
        return view
    d = {
        "status": delivery.status.value,
        "landmark": delivery.address_landmark,
        "notes": delivery.address_notes,
        "dropoff": ({"latitude": delivery.dropoff_latitude, "longitude": delivery.dropoff_longitude}
                    if delivery.dropoff_latitude is not None else None),
        "address_confirmed": delivery.address_confirmed_at is not None,
        "rider_name": rider.full_name.split()[0] if rider and delivery.status != S.UNASSIGNED else None,
        "rider_phone": rider.phone if rider and delivery.status in (S.EN_ROUTE, S.ARRIVED) else None,
        "rider_position": None,
        "eta_minutes": None,
        "delivered_at": delivery.delivered_at,
    }
    seen = _aware(delivery.last_location_at)
    fresh = seen and (_now() - seen).total_seconds() <= settings.TRACKING_FRESH_SECONDS
    if delivery.status in (S.EN_ROUTE, S.ARRIVED) and fresh and delivery.last_latitude is not None:
        d["rider_position"] = {"latitude": delivery.last_latitude, "longitude": delivery.last_longitude,
                               "updated_seconds_ago": int((_now() - seen).total_seconds())}
        if delivery.status == S.EN_ROUTE and delivery.dropoff_latitude is not None:
            d["eta_minutes"] = eta_minutes((delivery.last_latitude, delivery.last_longitude),
                                           (delivery.dropoff_latitude, delivery.dropoff_longitude))
    view["delivery"] = d
    return view
