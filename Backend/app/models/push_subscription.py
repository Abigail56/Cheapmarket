import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlmodel import Field

from app.models.base import UUIDBase, utcnow


class PushSubscription(UUIDBase, table=True):
    """One browser/phone that agreed to receive push alerts for a user (the rider app)."""
    __tablename__ = "push_subscriptions"

    user_id: uuid.UUID = Field(foreign_key="users.id", ondelete="CASCADE", index=True)
    endpoint: str = Field(sa_type=Text, unique=True)  # the push service URL for this device
    p256dh: str = Field(max_length=200)  # the browser's public key (payloads are encrypted to it)
    auth: str = Field(max_length=100)
    user_agent: str | None = Field(default=None, max_length=300)
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
    last_success_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
