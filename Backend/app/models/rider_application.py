import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, LargeBinary
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import TimestampMixin, UUIDBase, enum_type


class ApplicationStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class VehicleType(str, enum.Enum):
    MOTORCYCLE = "motorcycle"
    BICYCLE = "bicycle"
    TRICYCLE = "tricycle"  # keke
    CAR = "car"
    VAN = "van"


class IdType(str, enum.Enum):
    NIN = "nin"
    DRIVERS_LICENCE = "drivers_licence"
    VOTERS_CARD = "voters_card"
    PASSPORT = "passport"


class DocumentKind(str, enum.Enum):
    ID_FRONT = "id_front"
    ID_BACK = "id_back"
    SELFIE = "selfie"


class IdCheckStatus(str, enum.Enum):
    PENDING = "pending"                # queued, not run yet
    VERIFIED = "verified"              # government record found, face and name match
    REVIEW = "review"                  # something doesn't add up: an admin should look closely
    FAILED = "failed"                  # the ID doesn't exist in government records
    MANUAL = "manual"                  # no automatic government check for this ID: check by hand
    ERROR = "error"                    # the provider couldn't answer (retry with "Check again")


class RiderApplicationBase(SQLModel):
    vehicle_type: VehicleType = Field(sa_type=enum_type(VehicleType))
    id_type: IdType | None = Field(default=None, sa_type=enum_type(IdType))
    id_number: str | None = Field(default=None, max_length=40)
    plate_number: str | None = Field(default=None, max_length=20)
    area: str | None = Field(default=None, max_length=120)  # where they want to work
    note: str | None = Field(default=None, max_length=500)  # anything else they want to say


class RiderApplication(UUIDBase, TimestampMixin, RiderApplicationBase, table=True):
    """Someone who signed up in the rider app. Their user account exists (role rider)
    but can't sign in until an admin approves this."""
    __tablename__ = "rider_applications"

    user_id: uuid.UUID = Field(foreign_key="users.id", ondelete="CASCADE", unique=True)
    status: ApplicationStatus = Field(
        default=ApplicationStatus.PENDING, sa_type=enum_type(ApplicationStatus), index=True
    )
    reviewed_by: uuid.UUID | None = Field(default=None, foreign_key="users.id", ondelete="SET NULL")
    reviewed_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    reject_reason: str | None = Field(default=None, max_length=255)

    # ID check result. Only the registered name and the scores are kept: never the
    # government photo, date of birth or phone the provider returns.
    id_check_status: IdCheckStatus = Field(
        default=IdCheckStatus.PENDING, sa_type=enum_type(IdCheckStatus),
        sa_column_kwargs={"server_default": "pending"})
    id_check_reasons: list | None = Field(default=None, sa_type=JSONB)
    id_record_name: str | None = Field(default=None, max_length=200)
    id_name_match: int | None = None    # 0-100
    id_face_match: float | None = None  # provider's confidence, 0-100
    id_check_provider: str | None = Field(default=None, max_length=20)
    id_checked_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))


class RiderDocument(UUIDBase, table=True):
    """An ID photo or selfie from a rider application. Kept in the database (not in
    public /media) so it has no public URL; only admins can fetch it, and each view is
    audited. Deleted with the application."""
    __tablename__ = "rider_documents"

    application_id: uuid.UUID = Field(foreign_key="rider_applications.id", ondelete="CASCADE",
                                      index=True)
    kind: DocumentKind = Field(sa_type=enum_type(DocumentKind))
    content_type: str = Field(max_length=50)
    size: int
    data: bytes = Field(sa_type=LargeBinary)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC),
                                 sa_type=DateTime(timezone=True))
