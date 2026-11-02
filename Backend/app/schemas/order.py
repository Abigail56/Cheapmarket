import uuid
from datetime import datetime

from pydantic import EmailStr, field_validator, model_validator
from sqlmodel import Field, SQLModel

from app.models.order import OrderBase, OrderItemBase, PaymentMethod
from app.schemas.base import ReadModel
from app.utils.money import Money
from app.utils.phone import normalize_phone


class OrderItemRead(OrderItemBase, ReadModel):
    pass


class OrderRead(OrderBase, ReadModel):
    id: uuid.UUID
    created_at: datetime
    items: list[OrderItemRead]
    tracking_token: str  # the key to /track/<token>; only sent to people who can see the order


class QuoteRequest(SQLModel):
    zone_id: uuid.UUID
    coupon_code: str | None = Field(default=None, max_length=40)


class QuoteRead(SQLModel):
    subtotal: Money
    delivery_fee: Money
    discount_total: Money
    total: Money
    coupon_applied: str | None
    free_delivery_remaining: Money | None = Field(
        description="How much more to spend for free delivery, if the zone offers it"
    )


class CheckoutRequest(SQLModel):
    customer_name: str = Field(min_length=2, max_length=150)
    customer_phone: str = Field(min_length=7, max_length=20)
    customer_email: EmailStr | None = None
    address_id: uuid.UUID | None = Field(default=None, description="A saved address (logged-in users)")
    delivery_address: str | None = Field(default=None, min_length=5, max_length=500)
    zone_id: uuid.UUID | None = None
    payment_method: PaymentMethod
    coupon_code: str | None = Field(default=None, max_length=40)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("customer_phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)

    @model_validator(mode="after")
    def _need_address(self):
        if not self.address_id and not self.delivery_address:
            raise ValueError("Provide either address_id or delivery_address")
        if not self.address_id and not self.zone_id:
            raise ValueError("zone_id is required when delivery_address is typed in")
        return self


class CheckoutResponse(SQLModel):
    order: OrderRead
    payment_instructions: dict | None = None
    next_step: str = Field(description="pay_online | pay_on_delivery | bank_transfer")


class TrackRequest(SQLModel):
    order_number: str
    phone: str

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return normalize_phone(v)


class CancelRequest(SQLModel):
    phone: str | None = Field(default=None, description="Guests must provide the order phone")
    reason: str | None = Field(default=None, max_length=255)
