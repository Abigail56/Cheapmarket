import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index
from sqlmodel import Field

from app.models.base import UUIDBase, utcnow


class Notification(UUIDBase, table=True):
    """One line in someone's notification bell (admin dashboard or rider app)."""
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    user_id: uuid.UUID = Field(foreign_key="users.id", ondelete="CASCADE")
    kind: str = Field(max_length=40)  # the live event it came from, e.g. "order.placed"
    title: str = Field(max_length=150)
    body: str = Field(max_length=500)
    order_number: str | None = Field(default=None, max_length=40)
    read_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
    created_at: datetime = Field(default_factory=utcnow, sa_type=DateTime(timezone=True))
