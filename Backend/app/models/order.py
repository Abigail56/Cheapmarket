import enum
import secrets
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, DateTime, Numeric, Text
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UUIDBase, enum_type, utcnow
from app.utils.money import Money

if TYPE_CHECKING:
    from app.models.coupon import Coupon
    from app.models.delivery import Delivery
    from app.models.payment import Payment
    from app.models.product import Product
    from app.models.user import User


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PACKED = "packed"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class PaymentMethod(str, enum.Enum):
    COD = "cod"
    CARD = "card"
    TRANSFER = "transfer"


class PaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


class OrderBase(SQLModel):
    order_number: str = Field(max_length=30, unique=True, index=True)  # e.g. CMD-10482

    # Snapshots: stay correct even if the user edits their profile/address later
    customer_name: str = Field(max_length=150)
    customer_phone: str = Field(max_length=20)
    customer_email: str | None = Field(default=None, max_length=255)
    delivery_address: str = Field(sa_type=Text)

    status: OrderStatus = Field(
        default=OrderStatus.PENDING, sa_type=enum_type(OrderStatus), index=True
    )
    payment_method: PaymentMethod = Field(sa_type=enum_type(PaymentMethod))
    payment_status: PaymentStatus = Field(
        default=PaymentStatus.UNPAID, sa_type=enum_type(PaymentStatus), index=True
    )

    subtotal: Money = Field(sa_type=Numeric(12, 2))
    delivery_fee: Money = Field(default=Decimal(0), sa_type=Numeric(12, 2))
    discount_total: Money = Field(default=Decimal(0), sa_type=Numeric(12, 2))
    total: Money = Field(sa_type=Numeric(12, 2))
    notes: str | None = Field(default=None, sa_type=Text)


class Order(UUIDBase, TimestampMixin, OrderBase, table=True):
    __tablename__ = "orders"
    __table_args__ = (CheckConstraint("total >= 0", name="ck_orders_total_nonneg"),)

    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL", index=True
    )
    zone_id: uuid.UUID | None = Field(
        default=None, foreign_key="delivery_zones.id", ondelete="SET NULL"
    )
    coupon_id: uuid.UUID | None = Field(
        default=None, foreign_key="coupons.id", ondelete="SET NULL"
    )
    # Unguessable id for the customer's public tracking link (/track/<token>)
    tracking_token: str = Field(
        default_factory=lambda: secrets.token_urlsafe(16), max_length=32, unique=True, index=True
    )

    user: Optional["User"] = Relationship(back_populates="orders")
    coupon: Optional["Coupon"] = Relationship()
    items: list["OrderItem"] = Relationship(
        back_populates="order",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )
    payments: list["Payment"] = Relationship(back_populates="order")
    status_history: list["OrderStatusHistory"] = Relationship(back_populates="order")
    delivery: Optional["Delivery"] = Relationship(
        back_populates="order", sa_relationship_kwargs={"uselist": False}
    )


class OrderItemBase(SQLModel):
    product_id: uuid.UUID | None = Field(
        default=None, foreign_key="products.id", ondelete="SET NULL"
    )
    product_name: str = Field(max_length=200)  # snapshot
    unit_price: Money = Field(sa_type=Numeric(12, 2))  # snapshot
    quantity: int
    line_total: Money = Field(sa_type=Numeric(12, 2))


class OrderItem(UUIDBase, OrderItemBase, table=True):
    __tablename__ = "order_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="ck_order_items_qty_positive"),)

    order_id: uuid.UUID = Field(foreign_key="orders.id", ondelete="CASCADE", index=True)

    order: "Order" = Relationship(back_populates="items")
    product: Optional["Product"] = Relationship()


class OrderStatusHistoryBase(SQLModel):
    changed_by: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )
    status: OrderStatus = Field(sa_type=enum_type(OrderStatus))
    note: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class OrderStatusHistory(UUIDBase, OrderStatusHistoryBase, table=True):
    __tablename__ = "order_status_history"

    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)

    order: "Order" = Relationship(back_populates="status_history")
