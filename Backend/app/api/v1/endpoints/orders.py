from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import CartOwnerDep, CurrentUser, OptionalUser, SessionDep, rate_limit
from app.core.exceptions import BadRequest
from app.models.order import Order, OrderStatus
from app.schemas.order import (
    CancelRequest,
    CheckoutRequest,
    CheckoutResponse,
    OrderRead,
    QuoteRead,
    QuoteRequest,
    TrackRequest,
)
from app.services import order_service
from app.utils.pagination import Page, PageParams

router = APIRouter(tags=["ORDERS"])


@router.post("/checkout/quote", response_model=QuoteRead)
async def quote(data: QuoteRequest, owner: CartOwnerDep, session: SessionDep):
    """Price the current cart for a delivery zone (and optional coupon) before ordering."""
    return await order_service.quote(session, owner, data.zone_id, data.coupon_code)


@router.post(
    "/orders",
    response_model=CheckoutResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("checkout", 20))],
)
async def checkout(data: CheckoutRequest, owner: CartOwnerDep, session: SessionDep):
    """Turns the cart into an order. Works for guests (X-Cart-Session) and logged-in users.
    Totals are always calculated on the server."""
    order, instructions, next_step = await order_service.checkout(session, owner, data)
    return CheckoutResponse(order=OrderRead.model_validate(order),
                            payment_instructions=instructions, next_step=next_step)


@router.get("/orders", response_model=Page[OrderRead])
async def my_orders(
    user: CurrentUser, session: SessionDep, params: Annotated[PageParams, Depends()],
    status_filter: OrderStatus | None = Query(None, alias="status"),
):
    conds = [Order.user_id == user.id]
    if status_filter:
        conds.append(Order.status == status_filter)
    total = (await session.exec(select(func.count()).select_from(Order).where(*conds))).one()
    rows = (await session.exec(
        select(Order).where(*conds).order_by(Order.created_at.desc())
        .offset(params.offset).limit(params.size)
    )).all()
    return Page[OrderRead].build([OrderRead.model_validate(o) for o in rows], total, params)


@router.post("/orders/track", response_model=OrderRead,
             dependencies=[Depends(rate_limit("track", 20))])
async def track_order(data: TrackRequest, user: OptionalUser, session: SessionDep):
    """Guests look up an order with its number + the phone number used at checkout."""
    return await order_service.get_for_access(session, data.order_number, user, data.phone)


@router.get("/orders/{order_number}", response_model=OrderRead)
async def get_order(order_number: str, user: CurrentUser, session: SessionDep):
    return await order_service.get_for_access(session, order_number, user, None)


@router.post("/orders/{order_number}/cancel", response_model=OrderRead,
             dependencies=[Depends(rate_limit("cancel", 20))])
async def cancel_order(
    order_number: str, user: OptionalUser, session: SessionDep, data: CancelRequest | None = None,
):
    data = data or CancelRequest()
    order = await order_service.get_for_access(session, order_number, user, data.phone)
    if order.status not in order_service.CUSTOMER_CANCELLABLE:
        raise BadRequest(
            "This order can no longer be cancelled online. Please contact support.",
            code="not_cancellable",
        )
    return await order_service.change_status(
        session, order, OrderStatus.CANCELLED, user, data.reason or "Cancelled by customer"
    )
