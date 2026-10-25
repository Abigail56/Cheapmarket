import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field, Relationship

from app.models.base import TimestampMixin, UUIDBase

if TYPE_CHECKING:
    from app.models.product import Product
    from app.models.user import User


class Cart(UUIDBase, TimestampMixin, table=True):
    __tablename__ = "carts"
    __table_args__ = (
        CheckConstraint(
            "user_id IS NOT NULL OR session_id IS NOT NULL", name="ck_carts_has_owner"
        ),
    )

    user_id: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="CASCADE", unique=True
    )
    session_id: str | None = Field(default=None, max_length=64, unique=True)

    user: Optional["User"] = Relationship(back_populates="cart")
    items: list["CartItem"] = Relationship(
        back_populates="cart",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "lazy": "selectin"},
    )


class CartItem(UUIDBase, table=True):
    __tablename__ = "cart_items"
    __table_args__ = (
        UniqueConstraint("cart_id", "product_id", name="uq_cart_items_cart_product"),
        CheckConstraint("quantity > 0", name="ck_cart_items_qty_positive"),
    )

    cart_id: uuid.UUID = Field(foreign_key="carts.id", ondelete="CASCADE", index=True)
    product_id: uuid.UUID = Field(foreign_key="products.id", ondelete="CASCADE")
    quantity: int = Field(default=1)

    cart: "Cart" = Relationship(back_populates="items")
    product: "Product" = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
