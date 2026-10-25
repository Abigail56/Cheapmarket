import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Numeric, Text
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UUIDBase
from app.utils.money import Money

if TYPE_CHECKING:
    from app.models.category import Category


class ProductBase(SQLModel):
    """Fields every product schema shows. `category_id`, `stock_qty` and `is_active`
    are left out because the public ProductRead hides them."""
    name: str = Field(min_length=2, max_length=200, index=True)
    slug: str = Field(max_length=220, unique=True, index=True)
    description: str | None = Field(default=None, sa_type=Text)
    unit: str = Field(min_length=1, max_length=50)  # e.g. "1 kg", "crate of 30"
    price: Money = Field(ge=0, max_digits=12, decimal_places=2, sa_type=Numeric(12, 2))
    compare_at_price: Money | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2, sa_type=Numeric(12, 2)
    )
    image_url: str | None = Field(default=None, max_length=500)
    is_featured: bool = Field(default=False, index=True)


class Product(UUIDBase, TimestampMixin, ProductBase, table=True):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_products_price_nonneg"),
        CheckConstraint("stock_qty >= 0", name="ck_products_stock_nonneg"),
    )

    category_id: uuid.UUID = Field(foreign_key="categories.id", index=True)
    stock_qty: int = Field(default=0)
    is_active: bool = Field(default=True, index=True)

    category: "Category" = Relationship(
        back_populates="products", sa_relationship_kwargs={"lazy": "selectin"}
    )
