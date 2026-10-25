import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import model_validator
from sqlmodel import Field, SQLModel

from app.models.audit_log import AuditLogBase
from app.models.coupon import CouponBase, DiscountType
from app.models.delivery import DeliveryBase, DeliveryStatus
from app.models.order import OrderStatus, OrderStatusHistoryBase
from app.models.payment import PaymentBase
from app.models.rider_application import (
    ApplicationStatus,
    DocumentKind,
    IdCheckStatus,
    RiderApplicationBase,
)
from app.models.user import UserRole
from app.schemas.auth import RegisterRequest
from app.schemas.base import ReadModel
from app.schemas.order import OrderRead
from app.utils.money import Money


class OrderStatusUpdate(SQLModel):
    status: OrderStatus
    note: str | None = Field(default=None, max_length=255)


class MarkPaid(SQLModel):
    note: str | None = Field(default=None, max_length=255)


class AssignRider(SQLModel):
    rider_id: uuid.UUID


class HistoryRead(OrderStatusHistoryBase, ReadModel):
    pass


class PaymentRead(PaymentBase, ReadModel):
    pass


class DeliveryRead(DeliveryBase, ReadModel):
    id: uuid.UUID


class OrderAdminRead(OrderRead):
    history: list[HistoryRead] = []
    payments: list[PaymentRead] = []
    delivery: DeliveryRead | None = None


class CouponCreate(CouponBase):
    @model_validator(mode="after")
    def _check(self):
        self.code = self.code.strip().upper()
        if self.discount_type == DiscountType.PERCENT and self.value > 100:
            raise ValueError("A percentage discount cannot exceed 100")
        return self


class CouponUpdate(SQLModel):
    value: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    min_order: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    max_uses: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None
    is_active: bool | None = None


class CouponRead(CouponBase, ReadModel):
    id: uuid.UUID
    used_count: int


class AdminUserCreate(RegisterRequest):
    """An admin creating a staff account. Defaults to another admin."""
    role: UserRole = UserRole.ADMIN


class UserAdminUpdate(SQLModel):
    role: UserRole | None = None
    is_active: bool | None = None


class DashboardRead(SQLModel):
    orders_today: int
    revenue_today: Money
    orders_total: int
    revenue_total: Money
    pending_orders: int
    orders_by_status: dict[str, int]
    low_stock: list[dict]


class RiderDeliveryUpdate(SQLModel):
    status: DeliveryStatus


class AuditLogRead(AuditLogBase, ReadModel):
    id: uuid.UUID


class RiderDocumentInfo(SQLModel):
    id: uuid.UUID
    kind: DocumentKind
    content_type: str
    size: int


class RiderApplicationRead(RiderApplicationBase, ReadModel):
    id: uuid.UUID
    status: ApplicationStatus
    full_name: str
    email: str
    phone: str | None
    created_at: datetime
    reviewed_at: datetime | None
    reject_reason: str | None
    documents: list[RiderDocumentInfo] = []
    id_check_status: IdCheckStatus
    id_check_reasons: list[str] | None
    id_record_name: str | None
    id_name_match: int | None
    id_face_match: float | None
    id_checked_at: datetime | None


class RejectApplication(SQLModel):
    reason: str = Field(min_length=3, max_length=255,
                        description="Shown to the applicant (by SMS and when they try to sign in)")
