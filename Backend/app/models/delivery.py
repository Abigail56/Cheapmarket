import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import UUIDBase, enum_type, utcnow

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.user import User


class DeliveryStatus(str, enum.Enum):
    UNASSIGNED = "unassigned"  # rider declined or didn't answer in time: admin reassigns
    ASSIGNED = "assigned"      # waiting for the rider to accept
    ACCEPTED = "accepted"      # rider accepted; confirms the address next
    EN_ROUTE = "en_route"      # journey started (order is out_for_delivery)
    ARRIVED = "arrived"        # at the address; delivery code + photo next
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"    # the order was cancelled


ACTIVE_STATUSES = (DeliveryStatus.ASSIGNED, DeliveryStatus.ACCEPTED,
                   DeliveryStatus.EN_ROUTE, DeliveryStatus.ARRIVED)
_TZ = DateTime(timezone=True)


class DeliveryBase(SQLModel):
    """What admins may see. The delivery-code hash lives only on the table."""
    order_id: uuid.UUID = Field(foreign_key="orders.id", unique=True)
    rider_id: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL", index=True
    )
    status: DeliveryStatus = Field(
        default=DeliveryStatus.ASSIGNED, sa_type=enum_type(DeliveryStatus)
    )
    assigned_at: datetime = Field(default_factory=utcnow, sa_type=_TZ)
    accept_deadline: datetime | None = Field(default=None, sa_type=_TZ)
    accepted_at: datetime | None = Field(default=None, sa_type=_TZ)
    started_at: datetime | None = Field(default=None, sa_type=_TZ)
    arrived_at: datetime | None = Field(default=None, sa_type=_TZ)
    delivered_at: datetime | None = Field(default=None, sa_type=_TZ)

    # The confirmed drop-off. order.delivery_address (what the customer typed) never changes.
    dropoff_latitude: float | None = None
    dropoff_longitude: float | None = None
    address_landmark: str | None = Field(default=None, max_length=255)
    address_notes: str | None = Field(default=None, max_length=500)
    address_confirmed_at: datetime | None = Field(default=None, sa_type=_TZ)
    address_corrected_at: datetime | None = Field(default=None, sa_type=_TZ)  # by the customer

    # Latest GPS ping from the rider while the delivery is active
    last_latitude: float | None = None
    last_longitude: float | None = None
    last_location_at: datetime | None = Field(default=None, sa_type=_TZ)

    # Proof of delivery
    code_sent_at: datetime | None = Field(default=None, sa_type=_TZ)
    proof_photo_url: str | None = Field(default=None, max_length=500)
    delivered_latitude: float | None = None
    delivered_longitude: float | None = None
    geofence_override_at: datetime | None = Field(default=None, sa_type=_TZ)
    geofence_override_reason: str | None = Field(default=None, max_length=255)
    failure_reason: str | None = Field(default=None, max_length=255)


class Delivery(UUIDBase, DeliveryBase, table=True):
    __tablename__ = "deliveries"

    # HMAC of the 6-digit code, bound to this delivery. The code itself is never stored.
    code_hash: str | None = Field(default=None, max_length=64)
    code_expires_at: datetime | None = Field(default=None, sa_type=_TZ)
    code_attempts: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    geofence_override_by: uuid.UUID | None = Field(
        default=None, foreign_key="users.id", ondelete="SET NULL"
    )

    order: "Order" = Relationship(back_populates="delivery")
    rider: Optional["User"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "Delivery.rider_id"}
    )
