import uuid

from sqlmodel import Field, SQLModel

from app.schemas.catalog import ProductRead
from app.utils.money import Money


class CartItemAdd(SQLModel):
    product_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=100)


class CartItemSet(SQLModel):
    quantity: int = Field(ge=0, le=100, description="0 removes the item")


class CartItemRead(SQLModel):
    product: ProductRead
    quantity: int
    line_total: Money


class CartRead(SQLModel):
    session_id: str | None = Field(
        description="Guests: send this back in the X-Cart-Session header on every cart/checkout call"
    )
    items: list[CartItemRead]
    item_count: int
    subtotal: Money
    notices: list[str] = Field(default_factory=list, description="e.g. quantity reduced to stock")


class CartMerge(SQLModel):
    session_id: str = Field(min_length=16, max_length=64)
