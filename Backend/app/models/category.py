import uuid
from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UUIDBase

if TYPE_CHECKING:
    from app.models.product import Product


class CategoryBase(SQLModel):
    parent_id: uuid.UUID | None = Field(
        default=None, foreign_key="categories.id", ondelete="SET NULL", index=True
    )
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(max_length=120, unique=True, index=True)
    image_url: str | None = Field(default=None, max_length=500)
    sort_order: int = Field(default=0)
    is_active: bool = Field(default=True)


class Category(UUIDBase, TimestampMixin, CategoryBase, table=True):
    __tablename__ = "categories"

    products: list["Product"] = Relationship(back_populates="category")
