import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.money import Money


class Position(SQLModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0, description="GPS accuracy in metres")


class ConfirmAddress(Position):
    """The rider's check of the drop-off: the pin, plus anything the customer said on the phone."""
    landmark: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class CustomerAddressFix(SQLModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    landmark: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class Reason(SQLModel):
    reason: str = Field(min_length=3, max_length=255)


class OptionalReason(SQLModel):
    reason: str | None = Field(default=None, max_length=255)


class JobItem(SQLModel):
    name: str
    quantity: int


class RiderJob(SQLModel):
    """One delivery as the rider app shows it."""
    id: uuid.UUID
    status: str
    order_number: str
    order_status: str
    assigned_at: datetime
    accept_deadline: datetime | None
    customer_name: str
    customer_phone: str | None = Field(description="Shown once you accept")
    delivery_address: str
    landmark: str | None
    notes: str | None
    dropoff_latitude: float | None
    dropoff_longitude: float | None
    address_confirmed: bool
    customer_changed_address: bool
    items: list[JobItem]
    total: Money
    payment_method: str
    collect_cash: Money | None = Field(description="Cash to collect on delivery, if any")
    code_sent_at: datetime | None
    location_check_waived: bool


class CodeSent(SQLModel):
    sent: bool
    expires_in_minutes: int


class PushKeys(SQLModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=100)


class PushSubscribe(SQLModel):
    """Exactly what the browser's PushSubscription.toJSON() gives."""
    endpoint: str = Field(max_length=2000)
    keys: PushKeys


class PushUnsubscribe(SQLModel):
    endpoint: str = Field(max_length=2000)
