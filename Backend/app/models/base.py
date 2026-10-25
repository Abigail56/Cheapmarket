import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def enum_type(enum_cls: type) -> SAEnum:
    """Store enums as plain VARCHAR (no native PG enum), so adding a value later
    doesn't need a painful ALTER TYPE migration."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class UUIDBase(SQLModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(
        default_factory=utcnow, sa_type=DateTime(timezone=True), nullable=False
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": utcnow},
        nullable=False,
    )
