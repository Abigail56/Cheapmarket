from pydantic import field_validator
from sqlmodel import Field, SQLModel

from app.models.payment import PaymentProvider
from app.utils.phone import normalize_phone


class PaymentInitRequest(SQLModel):
    order_number: str
    provider: PaymentProvider = PaymentProvider.PAYSTACK
    phone: str | None = Field(default=None, description="Guests: the order's phone number")

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else None


class PaymentInitResponse(SQLModel):
    authorization_url: str = Field(description="Redirect the customer here to pay")
    reference: str
    mock: bool = False
