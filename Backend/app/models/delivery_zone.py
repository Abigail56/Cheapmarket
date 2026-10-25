from decimal import Decimal

from sqlalchemy import Numeric
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin, UUIDBase
from app.utils.money import Money


class DeliveryZoneBase(SQLModel):
    name: str = Field(min_length=2, max_length=100, unique=True, index=True)
    delivery_fee: Money = Field(
        default=Decimal(0), ge=0, max_digits=12, decimal_places=2, sa_type=Numeric(12, 2)
    )
    # Orders at or above this subtotal get free delivery in this zone (None = never free)
    free_delivery_min: Money | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2, sa_type=Numeric(12, 2)
    )
    is_active: bool = Field(default=True)


class DeliveryZone(UUIDBase, TimestampMixin, DeliveryZoneBase, table=True):
    __tablename__ = "delivery_zones"
