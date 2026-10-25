import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin, UUIDBase, enum_type
from app.utils.money import Money


class DiscountType(str, enum.Enum):
    PERCENT = "percent"
    FIXED = "fixed"


class CouponBase(SQLModel):
    code: str = Field(min_length=3, max_length=40, unique=True, index=True)
    discount_type: DiscountType = Field(sa_type=enum_type(DiscountType))
    value: Money = Field(gt=0, max_digits=12, decimal_places=2, sa_type=Numeric(12, 2))
    min_order: Money = Field(
        default=Decimal(0), ge=0, max_digits=12, decimal_places=2, sa_type=Numeric(12, 2)
    )
    max_uses: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    is_active: bool = Field(default=True)


class Coupon(UUIDBase, TimestampMixin, CouponBase, table=True):
    __tablename__ = "coupons"

    used_count: int = Field(default=0)
