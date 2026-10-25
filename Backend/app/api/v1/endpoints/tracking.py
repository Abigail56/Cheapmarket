"""The customer's tracking link. No login: the unguessable token in the link is the key."""
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlmodel import select

from app.api.deps import SessionDep, rate_limit
from app.models.order import OrderStatusHistory
from app.models.user import User
from app.schemas.delivery import CustomerAddressFix
from app.services import delivery_service, events

router = APIRouter(prefix="/track", tags=["TRACKING"])


async def _view(session, token: str) -> dict:
    order = await delivery_service.order_by_token(session, token)
    delivery = await delivery_service.delivery_for_order(session, order)
    history = (await session.exec(select(OrderStatusHistory).where(
        OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at))).all()
    rider = await session.get(User, delivery.rider_id) if delivery and delivery.rider_id else None
    return delivery_service.tracking_view(order, delivery, list(history), rider)


@router.get("/{token}", dependencies=[Depends(rate_limit("track-view", 120))])
async def track(token: str, session: SessionDep) -> dict:
    """Order status, timeline, and the rider on the map while they're on the way."""
    return await _view(session, token)


@router.post("/{token}/address", dependencies=[Depends(rate_limit("track-address", 10))])
async def fix_address(token: str, data: CustomerAddressFix, session: SessionDep) -> dict:
    """Correct the landmark/notes or drop a pin, until the rider sets off."""
    order = await delivery_service.order_by_token(session, token)
    await delivery_service.customer_correct_address(
        session, order, latitude=data.latitude, longitude=data.longitude,
        landmark=data.landmark, notes=data.notes)
    return await _view(session, token)


@router.get("/{token}/events")
async def track_events(token: str, request: Request, session: SessionDep,
                       last_event_id: Annotated[str | None, Header()] = None):
    """Live updates for the tracking page (status changes and, while on the way, the rider's position)."""
    order = await delivery_service.order_by_token(session, token)
    return events.response(request, events.track_stream(order.id), last_event_id)
