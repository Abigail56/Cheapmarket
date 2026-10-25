import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import UUIDBase, enum_type, utcnow
from app.utils.money import Money

if TYPE_CHECKING:
    from app.models.order import Order


class PaymentProvider(str, enum.Enum):
    PAYSTACK = "paystack"
    FLUTTERWAVE = "flutterwave"
    TRANSFER = "transfer"
    COD = "cod"


class PaymentRecordStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class PaymentBase(SQLModel):
    provider: PaymentProvider = Field(sa_type=enum_type(PaymentProvider))
    reference: str = Field(max_length=100, unique=True, index=True)
    amount: Money = Field(sa_type=Numeric(12, 2))
    status: PaymentRecordStatus = Field(
        default=PaymentRecordStatus.PENDING, sa_type=enum_type(PaymentRecordStatus)
    )
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))


class Payment(UUIDBase, PaymentBase, table=True):
    __tablename__ = "payments"

    order_id: uuid.UUID = Field(foreign_key="orders.id", index=True)
    raw_response: dict | None = Field(default=None, sa_type=JSONB)

    order: "Order" = Relationship(back_populates="payments")
