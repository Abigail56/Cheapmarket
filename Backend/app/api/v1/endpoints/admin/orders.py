from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlmodel import select

from app.api.deps import AdminUser, SessionDep
from app.core.config import settings
from app.core.exceptions import BadRequest, NotFound
from app.models.delivery import Delivery
from app.models.order import Order, OrderStatus, OrderStatusHistory, PaymentStatus
from app.models.payment import Payment
from app.models.product import Product
from app.models.user import User
from app.schemas.admin import (
    AssignRider,
    DashboardRead,
    DeliveryRead,
    HistoryRead,
    MarkPaid,
    OrderAdminRead,
    OrderStatusUpdate,
    PaymentRead,
)
from app.schemas.order import OrderRead
from app.services import audit, delivery_service, order_service, payment_service
from app.utils.money import q2
from app.utils.pagination import Page, PageParams

router = APIRouter(prefix="/admin", tags=["ADMIN: ORDERS"])


async def _detail(session, order: Order) -> OrderAdminRead:
    history = (await session.exec(select(OrderStatusHistory).where(
        OrderStatusHistory.order_id == order.id).order_by(OrderStatusHistory.created_at))).all()
    payments = (await session.exec(select(Payment).where(
        Payment.order_id == order.id).order_by(Payment.created_at))).all()
    delivery = (await session.exec(select(Delivery).where(Delivery.order_id == order.id))).first()
    base = OrderRead.model_validate(order).model_dump()
    return OrderAdminRead(
        **base,
        history=[HistoryRead.model_validate(h) for h in history],
        payments=[PaymentRead.model_validate(p) for p in payments],
        delivery=DeliveryRead.model_validate(delivery) if delivery else None,
    )


async def _order(session, order_number: str) -> Order:
    order = await order_service.find_by_number(session, order_number)
    if not order:
        raise NotFound("Order not found")
    return order


@router.get("/orders", response_model=Page[OrderRead])
async def list_orders(
    _: AdminUser, session: SessionDep, params: Annotated[PageParams, Depends()],
    status: OrderStatus | None = None,
    payment_status: PaymentStatus | None = None,
    q: str | None = Query(None, description="Order number, customer name or phone"),
    date_from: datetime | None = None, date_to: datetime | None = None,
):
    conds = []
    if status:
        conds.append(Order.status == status)
    if payment_status:
        conds.append(Order.payment_status == payment_status)
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(Order.order_number.ilike(like), Order.customer_name.ilike(like),
                         Order.customer_phone.ilike(like)))
    if date_from:
        conds.append(Order.created_at >= date_from)
    if date_to:
        conds.append(Order.created_at <= date_to)
    total = (await session.exec(select(func.count()).select_from(Order).where(*conds))).one()
    rows = (await session.exec(select(Order).where(*conds).order_by(Order.created_at.desc())
                               .offset(params.offset).limit(params.size))).all()
    return Page[OrderRead].build([OrderRead.model_validate(o) for o in rows], total, params)


@router.get("/orders/{order_number}", response_model=OrderAdminRead)
async def get_order(order_number: str, _: AdminUser, session: SessionDep):
    return await _detail(session, await _order(session, order_number))


@router.patch("/orders/{order_number}/status", response_model=OrderAdminRead)
async def update_status(order_number: str, data: OrderStatusUpdate, admin: AdminUser, session: SessionDep):
    order = await _order(session, order_number)
    audit.record(session, admin, "order.status", order, entity_id=order.order_number,
                 changes={"status": [order.status.value, data.status.value], "note": data.note})
    await order_service.change_status(session, order, data.status, admin, data.note)
    return await _detail(session, order)


@router.post("/orders/{order_number}/mark-paid", response_model=OrderAdminRead)
async def mark_paid(order_number: str, data: MarkPaid, admin: AdminUser, session: SessionDep):
    """For bank transfers (and cash collected). Card payments confirm themselves."""
    order = await _order(session, order_number)
    audit.record(session, admin, "order.mark_paid", order, entity_id=order.order_number,
                 changes={"payment_status": [order.payment_status.value, "paid"], "note": data.note})
    await payment_service.mark_manually_paid(session, order, admin, data.note)
    return await _detail(session, order)


@router.post("/orders/{order_number}/assign-rider", response_model=OrderAdminRead)
async def assign_rider(order_number: str, data: AssignRider, admin: AdminUser, session: SessionDep):
    """Offers the delivery to a rider, who must accept within RIDER_ACCEPT_SECONDS (5 min)
    or it comes back here. Also used to reassign."""
    order = await _order(session, order_number)
    rider = await session.get(User, data.rider_id)
    if not rider:
        raise BadRequest("That user is not an active rider")
    await delivery_service.assign(session, order, rider, admin)
    return await _detail(session, order)


@router.get("/dashboard", response_model=DashboardRead)
async def dashboard(_: AdminUser, session: SessionDep):
    start_today = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    live = Order.status != OrderStatus.CANCELLED
    paid = (Order.payment_status == PaymentStatus.PAID) & live

    async def one(stmt):
        return (await session.exec(stmt)).one()

    orders_today = await one(select(func.count()).select_from(Order)
                             .where(Order.created_at >= start_today, live))
    revenue_today = await one(select(func.coalesce(func.sum(Order.total), 0)).where(
        Order.created_at >= start_today, paid))
    orders_total = await one(select(func.count()).select_from(Order).where(live))
    revenue_total = await one(select(func.coalesce(func.sum(Order.total), 0)).where(paid))
    by_status = (await session.exec(select(Order.status, func.count()).group_by(Order.status))).all()
    low = (await session.exec(
        select(Product).where(Product.is_active.is_(True),
                              Product.stock_qty <= settings.LOW_STOCK_THRESHOLD)
        .order_by(Product.stock_qty).limit(20))).all()
    counts = {s.value: n for s, n in by_status}
    return DashboardRead(
        orders_today=orders_today, revenue_today=q2(Decimal(revenue_today)),
        orders_total=orders_total, revenue_total=q2(Decimal(revenue_total)),
        pending_orders=counts.get("pending", 0), orders_by_status=counts,
        low_stock=[{"id": str(p.id), "name": p.name, "stock_qty": p.stock_qty} for p in low],
    )
