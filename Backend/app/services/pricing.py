import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import BadRequest, NotFound
from app.models.coupon import Coupon, DiscountType
from app.models.delivery_zone import DeliveryZone
from app.models.product import Product
from app.utils.money import q2


@dataclass
class Pricing:
    zone: DeliveryZone
    subtotal: Decimal
    delivery_fee: Decimal
    discount: Decimal
    total: Decimal
    coupon: Coupon | None
    free_delivery_remaining: Decimal | None


def validate_lines(lines: list[tuple[Product, int]]) -> None:
    for product, qty in lines:
        if not product.is_active:
            raise BadRequest(f"'{product.name}' is no longer available", code="product_unavailable")
        if product.stock_qty < qty:
            raise BadRequest(
                f"Only {product.stock_qty} of '{product.name}' left in stock",
                code="insufficient_stock",
            )


async def load_coupon(
    session: AsyncSession, code: str, subtotal: Decimal, *, lock: bool = False
) -> Coupon:
    stmt = select(Coupon).where(Coupon.code == code.strip().upper())
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    coupon = (await session.exec(stmt)).first()
    if not coupon or not coupon.is_active:
        raise BadRequest("This coupon code is not valid", code="invalid_coupon")
    if coupon.expires_at and coupon.expires_at < datetime.now(UTC):
        raise BadRequest("This coupon has expired", code="coupon_expired")
    if coupon.max_uses is not None and coupon.used_count >= coupon.max_uses:
        raise BadRequest("This coupon has been fully redeemed", code="coupon_exhausted")
    if subtotal < coupon.min_order:
        raise BadRequest(
            f"This coupon needs a minimum order of {q2(coupon.min_order)}", code="coupon_min_order"
        )
    return coupon


async def compute(
    session: AsyncSession,
    lines: list[tuple[Product, int]],
    zone_id: uuid.UUID,
    coupon_code: str | None,
    *,
    lock_coupon: bool = False,
) -> Pricing:
    zone = await session.get(DeliveryZone, zone_id)
    if not zone or not zone.is_active:
        raise NotFound("Delivery zone not found")

    subtotal = q2(sum((p.price * qty for p, qty in lines), Decimal(0)))

    fee = q2(zone.delivery_fee)
    remaining: Decimal | None = None
    if zone.free_delivery_min is not None and fee > 0:
        if subtotal >= zone.free_delivery_min:
            fee = Decimal("0.00")
        else:
            remaining = q2(zone.free_delivery_min - subtotal)

    coupon, discount = None, Decimal("0.00")
    if coupon_code:
        coupon = await load_coupon(session, coupon_code, subtotal, lock=lock_coupon)
        if coupon.discount_type == DiscountType.PERCENT:
            discount = q2(subtotal * coupon.value / Decimal(100))
        else:
            discount = q2(coupon.value)
        discount = min(discount, subtotal)  # never discount the delivery fee or go negative

    total = q2(subtotal + fee - discount)
    return Pricing(zone, subtotal, fee, discount, total, coupon, remaining)
