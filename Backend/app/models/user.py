import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import TimestampMixin, UUIDBase, enum_type

if TYPE_CHECKING:
    from app.models.address import Address
    from app.models.cart import Cart
    from app.models.order import Order


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    CUSTOMER = "customer"
    RIDER = "rider"


class UserBase(SQLModel):
    email: str = Field(max_length=255, unique=True, index=True)
    phone: str | None = Field(default=None, max_length=20, unique=True, index=True)
    full_name: str = Field(min_length=2, max_length=150)


class User(UUIDBase, TimestampMixin, UserBase, table=True):
    __tablename__ = "users"

    password_hash: str = Field(max_length=255)
    role: UserRole = Field(
        default=UserRole.CUSTOMER, sa_type=enum_type(UserRole), index=True
    )
    is_active: bool = Field(default=True)
    phone_verified_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    # Every token carries this number; bumping it (password reset) logs out all sessions
    token_version: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    # Google's permanent id for this person, once they've used "Continue with Google"
    google_sub: str | None = Field(default=None, max_length=255, unique=True, index=True)

    addresses: list["Address"] = Relationship(
        back_populates="user", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    cart: "Cart" = Relationship(
        back_populates="user", sa_relationship_kwargs={"uselist": False}
    )
    orders: list["Order"] = Relationship(back_populates="user")
