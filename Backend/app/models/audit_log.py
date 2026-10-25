import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.models.base import UUIDBase, utcnow


class AuditLogBase(SQLModel):
    actor_id: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL", index=True
    )
    action: str = Field(max_length=50)  # e.g. "product.update"
    entity_type: str = Field(max_length=50)
    entity_id: str = Field(max_length=64)
    # {"field": [old, new]} for updates, the new values for creates
    changes: dict | None = Field(default=None, sa_type=JSONB)
    created_at: datetime = Field(
        default_factory=utcnow, sa_type=DateTime(timezone=True), index=True
    )


class AuditLog(UUIDBase, AuditLogBase, table=True):
    """Who changed what in the admin panel. Written in the same transaction as the change."""
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_entity", "entity_type", "entity_id"),)
