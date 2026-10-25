import secrets

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import CartOwner
from app.core.config import settings
from app.core.exceptions import BadRequest, NotFound
from app.models.address import Address
from app.models.coupon import Coupon
from app.models.delivery import ACTIVE_STATUSES, Delivery, DeliveryStatus
from app.models.order import (
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    PaymentMethod,
    PaymentStatus,
)
from app.models.payment import Payment, PaymentProvider, PaymentRecordStatus
from app.models.product import Product
from app.models.user import User, UserRole
from app.schemas.order import CheckoutRequest, QuoteRead
from app.services import cart_service, catalog_service, events, notifications, pricing
from app.utils.money import q2
from app.utils.phone import normalize_phone

S = OrderStatus
TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    S.PENDING: {S.CONFIRMED, S.CANCELLED},
    S.CONFIRMED: {S.PACKED, S.CANCELLED},
    S.PACKED: {S.OUT_FOR_DELIVERY, S.CANCELLED},
    S.OUT_FOR_DELIVERY: {S.DELIVERED, S.CANCELLED},
    S.DELIVERED: set(),
    S.CANCELLED: set(),
}
CUSTOMER_CANCELLABLE = {S.PENDING, S.CONFIRMED}


# ------------------------------- quote / checkout -----------------------------
async def _cart_lines(session: AsyncSession, owner: CartOwner, *, lock: bool):
    cart = await cart_service.find_cart(session, owner)
    if not cart or not cart.items:
        raise BadRequest("Your cart is empty", code="empty_cart")
    ids = sorted(i.product_id for i in cart.items)
    stmt = select(Product).where(Product.id.in_(ids)).order_by(Product.id)
    if lock:  # row locks, taken in id order to avoid deadlocks between concurrent checkouts
        stmt = stmt.with_for_update()
    stmt = stmt.execution_options(populate_existing=True)
    products = {p.id: p for p in (await session.exec(stmt)).all()}
    lines = [(products[i.product_id], i.quantity) for i in cart.items if i.product_id in products]
    pricing.validate_lines(lines)
    return cart, lines


async def quote(session: AsyncSession, owner: CartOwner, zone_id, coupon_code) -> QuoteRead:
    _, lines = await _cart_lines(session, owner, lock=False)
    p = await pricing.compute(session, lines, zone_id, coupon_code)
    return QuoteRead(
        subtotal=p.subtotal, delivery_fee=p.delivery_fee, discount_total=p.discount, total=p.total,
        coupon_applied=p.coupon.code if p.coupon else None,
        free_delivery_remaining=p.free_delivery_remaining,
    )


async def _new_order_number(session: AsyncSession) -> str:
    while True:
        number = f"{settings.ORDER_NUMBER_PREFIX}-{secrets.token_hex(4).upper()}"
        exists = (await session.exec(select(Order.id).where(Order.order_number == number))).first()
        if not exists:
            return number


async def checkout(
    session: AsyncSession, owner: CartOwner, data: CheckoutRequest
) -> tuple[Order, dict | None, str]:
    user = owner.user
    cart, lines = await _cart_lines(session, owner, lock=True)

    # Address + zone
    zone_id = data.zone_id
    if data.address_id:
        addr = await session.get(Address, data.address_id)
        if not user or not addr or addr.user_id != user.id:
            raise NotFound("Address not found")
        address_text = ", ".join(x for x in [addr.street, addr.landmark, addr.city, addr.state] if x)
        zone_id = zone_id or addr.zone_id
        if not zone_id:
            raise BadRequest("Choose a delivery zone", code="zone_required")
    else:
        address_text = data.delivery_address  # validated non-empty by the schema

    email = data.customer_email or (user.email if user else None)
    if data.payment_method == PaymentMethod.CARD and not email:
        raise BadRequest("An email address is required for card payments", code="email_required")

    p = await pricing.compute(session, lines, zone_id, data.coupon_code, lock_coupon=True)

    order = Order(
        order_number=await _new_order_number(session),
        user_id=user.id if user else None,
        zone_id=p.zone.id,
        coupon_id=p.coupon.id if p.coupon else None,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        customer_email=email,
        delivery_address=address_text,
        status=OrderStatus.PENDING,
        payment_method=data.payment_method,
        payment_status=PaymentStatus.UNPAID,
        subtotal=p.subtotal, delivery_fee=p.delivery_fee,
        discount_total=p.discount, total=p.total, notes=data.notes,
    )
    order.items = [
        OrderItem(
            product_id=prod.id, product_name=prod.name, unit_price=q2(prod.price),
            quantity=qty, line_total=q2(prod.price * qty),
        )
        for prod, qty in lines
    ]
    for prod, qty in lines:  # rows are locked, so this can't oversell
        prod.stock_qty -= qty
        session.add(prod)
    if p.coupon:
        p.coupon.used_count += 1
        session.add(p.coupon)

    session.add(order)
    session.add(OrderStatusHistory(order_id=order.id, status=OrderStatus.PENDING,
                                   note="Order placed", changed_by=user.id if user else None))

    instructions, next_step = None, "pay_online"
    if data.payment_method == PaymentMethod.COD:
        session.add(Payment(order_id=order.id, provider=PaymentProvider.COD,
                            reference=f"COD-{order.order_number}", amount=p.total))
        next_step = "pay_on_delivery"
    elif data.payment_method == PaymentMethod.TRANSFER:
        session.add(Payment(order_id=order.id, provider=PaymentProvider.TRANSFER,
                            reference=f"TRF-{order.order_number}", amount=p.total))
        next_step = "bank_transfer"
        instructions = {
            "bank_name": settings.BANK_NAME,
            "account_number": settings.BANK_ACCOUNT_NUMBER,
            "account_name": settings.BANK_ACCOUNT_NAME,
            "amount": float(p.total),
            "payment_reference": order.order_number,
            "note": "Use the order number as your transfer reference. "
                    "We confirm the order once the payment is received.",
        }

    for item in list(cart.items):  # empty the cart in the same transaction
        await session.delete(item)

    await session.commit()
    await catalog_service.invalidate_catalog_cache()  # stock changed
    await notifications.order_event(order, "placed")
    await events.publish([events.ADMIN], "order.placed",
                         {"order_id": order.id, "order_number": order.order_number,
                          "total": order.total, "payment_method": order.payment_method.value})
    return order, instructions, next_step


# ------------------------------- access / lookup ------------------------------
async def find_by_number(session: AsyncSession, order_number: str) -> Order | None:
    stmt = select(Order).where(Order.order_number == order_number.strip().upper())
    return (await session.exec(stmt)).first()


async def get_for_access(
    session: AsyncSession, order_number: str, user: User | None, phone: str | None
) -> Order:
    """Owner, admin, or a guest who knows the order number AND its phone number."""
    order = await find_by_number(session, order_number)
    allowed = bool(order) and (
        (user is not None and (order.user_id == user.id or user.role == UserRole.ADMIN))
        or (phone is not None and normalize_phone(phone) == order.customer_phone)
    )
    if not allowed:
        raise NotFound("Order not found")  # same answer whether or not the order exists
    return order


# ------------------------------- status machine -------------------------------
async def _restore_stock(session: AsyncSession, order: Order) -> None:
    ids = sorted(i.product_id for i in order.items if i.product_id)
    if ids:
        stmt = (select(Product).where(Product.id.in_(ids)).order_by(Product.id)
                .with_for_update().execution_options(populate_existing=True))
        products = {p.id: p for p in (await session.exec(stmt)).all()}
        for item in order.items:
            if item.product_id in products:
                products[item.product_id].stock_qty += item.quantity
                session.add(products[item.product_id])
    if order.coupon_id:
        coupon = await session.get(Coupon, order.coupon_id, with_for_update=True)
        if coupon and coupon.used_count > 0:
            coupon.used_count -= 1
            session.add(coupon)


async def set_payment_paid(
    session: AsyncSession, order: Order, provider: PaymentProvider, reference: str | None,
    raw: dict | None = None,
) -> None:
    """Marks the order paid and records it on the matching payment row."""
    stmt = select(Payment).where(Payment.order_id == order.id)
    if reference:
        stmt = stmt.where(Payment.reference == reference)
    payment = (await session.exec(stmt.order_by(Payment.created_at.desc()))).first()
    if payment is None:
        payment = Payment(order_id=order.id, provider=provider,
                          reference=reference or f"{provider.value.upper()}-{order.order_number}",
                          amount=order.total)
    payment.status = PaymentRecordStatus.SUCCESS
    if raw is not None:
        payment.raw_response = raw
    session.add(payment)
    order.payment_status = PaymentStatus.PAID
    session.add(order)


async def change_status(
    session: AsyncSession, order: Order, new_status: OrderStatus,
    actor: User | None, note: str | None = None,
) -> Order:
    old = order.status
    if new_status == old:
        raise BadRequest(f"Order is already {old.value}")
    if new_status not in TRANSITIONS[old]:
        raise BadRequest(f"Cannot move an order from {old.value} to {new_status.value}",
                         code="invalid_transition")
    if (old == OrderStatus.PENDING and new_status == OrderStatus.CONFIRMED
            and order.payment_method != PaymentMethod.COD
            and order.payment_status != PaymentStatus.PAID):
        raise BadRequest("This order must be paid before it can be confirmed", code="unpaid_order")

    if new_status == OrderStatus.CANCELLED:
        await _restore_stock(session, order)
        if order.payment_status == PaymentStatus.PAID:
            note = f"{note or 'Cancelled'} (order was paid: refund required)"
    if (new_status == OrderStatus.DELIVERED and order.payment_method == PaymentMethod.COD
            and order.payment_status == PaymentStatus.UNPAID):
        await set_payment_paid(session, order, PaymentProvider.COD, None)

    stopped_rider = None
    if new_status == OrderStatus.CANCELLED:  # call off an active delivery
        delivery = (await session.exec(select(Delivery).where(Delivery.order_id == order.id))).first()
        if delivery and delivery.status in ACTIVE_STATUSES:
            stopped_rider, delivery.status, delivery.code_hash = delivery.rider_id, DeliveryStatus.CANCELLED, None
            session.add(delivery)

    order.status = new_status
    session.add(order)
    session.add(OrderStatusHistory(order_id=order.id, status=new_status, note=note,
                                   changed_by=actor.id if actor else None))
    await session.commit()
    streams = [events.ADMIN, events.track_stream(order.id)]
    if stopped_rider:
        streams.append(events.rider_stream(stopped_rider))
        await notifications.push_rider(stopped_rider, f"Cancelled: {order.order_number}",
                                       "This order was cancelled. Don't deliver it.",
                                       tag=f"cancel-{order.id}")
    await events.publish(streams, "order.status_changed",
                         {"order_id": order.id, "order_number": order.order_number,
                          "status": new_status.value, "previous": old.value})
    if new_status == OrderStatus.CANCELLED:
        await catalog_service.invalidate_catalog_cache()
    if event := notifications.STATUS_EVENTS.get(new_status):
        await notifications.order_event(order, event)
    return order
