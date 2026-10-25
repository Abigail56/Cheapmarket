import uuid
from typing import TYPE_CHECKING, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UUIDBase

if TYPE_CHECKING:
    from app.models.delivery_zone import DeliveryZone
    from app.models.user import User


class AddressBase(SQLModel):
    """Fields shared by the table and the address API schemas."""
    zone_id: uuid.UUID | None = Field(
        default=None, foreign_key="delivery_zones.id", ondelete="SET NULL", index=True
    )
    label: str = Field(default="Home", max_length=50)
    street: str = Field(min_length=3, max_length=255)
    landmark: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    is_default: bool = Field(default=False)


class Address(UUIDBase, TimestampMixin, AddressBase, table=True):
    __tablename__ = "addresses"

    user_id: uuid.UUID = Field(foreign_key="users.id", ondelete="CASCADE", index=True)

    user: "User" = Relationship(back_populates="addresses")
    zone: Optional["DeliveryZone"] = Relationship()
