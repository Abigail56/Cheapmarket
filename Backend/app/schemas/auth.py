import uuid
from datetime import datetime

from pydantic import EmailStr, field_validator
from sqlmodel import Field, SQLModel

from app.models.address import AddressBase
from app.models.rider_application import IdType, VehicleType
from app.models.user import UserBase, UserRole
from app.schemas.base import ReadModel
from app.utils.phone import normalize_phone


class RegisterRequest(UserBase):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else None


class RefreshRequest(SQLModel):
    refresh_token: str


class HandoffRedeem(SQLModel):
    code: str = Field(max_length=100)


class TokenPair(SQLModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserRead(UserBase, ReadModel):
    id: uuid.UUID
    role: UserRole
    is_active: bool
    phone_verified_at: datetime | None
    created_at: datetime


class AuthResponse(TokenPair):
    """Register returns the new account and logs it in, same tokens as /auth/login."""
    user: UserRead


class UserUpdate(SQLModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else None


class _EmailLower(SQLModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.lower()


class LoginRequest(_EmailLower):
    password: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "email": "user@example.com",
                "password": "Passw0rd!x",
            }
        }
    }


class ForgotPasswordRequest(_EmailLower):
    """The email on the account; the reset code is emailed there."""


class ResetPasswordRequest(_EmailLower):
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8, max_length=128)


class PhoneVerifyConfirm(SQLModel):
    code: str = Field(min_length=6, max_length=6)


class ChangePasswordRequest(SQLModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class AddressCreate(AddressBase):
    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v else None


class AddressUpdate(SQLModel):
    label: str | None = Field(default=None, max_length=50)
    street: str | None = Field(default=None, min_length=3, max_length=255)
    landmark: str | None = None
    city: str | None = Field(default=None, min_length=2, max_length=100)
    state: str | None = Field(default=None, min_length=2, max_length=100)
    phone: str | None = None
    zone_id: uuid.UUID | None = None
    is_default: bool | None = None


class AddressRead(AddressBase, ReadModel):
    id: uuid.UUID


class RiderSignup(RegisterRequest):
    """'Become a rider' form. Phone is required: approval and offers are sent by SMS."""
    phone: str = Field(min_length=7, max_length=20)
    vehicle_type: VehicleType
    id_type: IdType
    id_number: str = Field(min_length=4, max_length=40)
    plate_number: str | None = Field(default=None, max_length=20)
    area: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("plate_number")
    @classmethod
    def _plate(cls, v: str | None) -> str | None:
        return v.strip().upper() or None if v else None

    @field_validator("id_number")
    @classmethod
    def _id_number(cls, v: str) -> str:
        return " ".join(v.split()).upper()


class GoogleSignIn(SQLModel):
    id_token: str = Field(min_length=20, max_length=4096, description="The `credential` Google's button returns")
    create_account: bool = Field(
        default=True, description="Create a customer account if none exists. The rider app and "
                                  "admin dashboard send false: they only sign existing people in.")
