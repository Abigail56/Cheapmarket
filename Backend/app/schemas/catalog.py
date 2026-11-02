import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import computed_field
from sqlmodel import Field, SQLModel

from app.models.category import CategoryBase
from app.models.delivery_zone import DeliveryZoneBase
from app.models.product import ProductBase
from app.schemas.base import ReadModel


class CategoryRead(CategoryBase, ReadModel):
    id: uuid.UUID


class CategoryBrief(SQLModel):
    id: uuid.UUID
    name: str
    slug: str


class ProductRead(ProductBase, ReadModel):
    id: uuid.UUID
    category: CategoryBrief
    stock_qty: int = Field(exclude=True)  # exact stock is not exposed publicly

    @computed_field  # type: ignore[prop-decorator]
    @property
    def in_stock(self) -> bool:
        return self.stock_qty > 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def discount_percent(self) -> int | None:
        if self.compare_at_price and self.compare_at_price > self.price:
            # the half allows for sale prices being rounded to whole naira: 15% off 1,001 stays "15%"
            return int((float(self.compare_at_price - self.price) + 0.5) / float(self.compare_at_price) * 100)
        return None


class ProductAdminRead(ProductRead):
    stock_qty: int  # type: ignore[assignment]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ZoneRead(DeliveryZoneBase, ReadModel):
    id: uuid.UUID


# ------------------------------ admin inputs ----------------------------------
class CategoryCreate(CategoryBase):
    slug: str | None = Field(default=None, max_length=120)  # generated from name if omitted


class CategoryUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    slug: str | None = Field(default=None, max_length=120)
    parent_id: uuid.UUID | None = None
    image_url: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class ProductCreate(ProductBase):
    category_id: uuid.UUID
    slug: str | None = Field(default=None, max_length=220)  # generated from name if omitted
    stock_qty: int = Field(default=0, ge=0)
    is_active: bool = True


class ProductUpdate(SQLModel):
    category_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=2, max_length=200)
    slug: str | None = Field(default=None, max_length=220)
    description: str | None = None
    unit: str | None = Field(default=None, min_length=1, max_length=50)
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    compare_at_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    image_url: str | None = None
    is_featured: bool | None = None
    is_active: bool | None = None


class DiscountApply(SQLModel):
    """Percentage off the normal price (0 ends the discount). Applies to `product_ids`,
    or to `category_id`, or to every product when neither is given."""
    percent: int = Field(ge=0, le=90)
    product_ids: list[uuid.UUID] | None = None
    category_id: uuid.UUID | None = None


class StockAdjust(SQLModel):
    """Provide exactly one: `set` (absolute) or `delta` (+/- change)."""
    set: int | None = Field(default=None, ge=0)
    delta: int | None = None


class ZoneCreate(DeliveryZoneBase):
    delivery_fee: Decimal = Field(ge=0, max_digits=12, decimal_places=2)  # required on create


class ZoneUpdate(SQLModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    delivery_fee: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    free_delivery_min: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    is_active: bool | None = None


ProductSort = Literal["newest", "price_asc", "price_desc", "name"]
