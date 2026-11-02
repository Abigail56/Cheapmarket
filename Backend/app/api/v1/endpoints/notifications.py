"""The notification bell. Everyone only ever sees and changes their own notifications."""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlmodel import SQLModel

from app.api.deps import CurrentUser, SessionDep
from app.core.exceptions import NotFound
from app.services import inbox

router = APIRouter(prefix="/notifications", tags=["NOTIFICATIONS"])


class NotificationRead(SQLModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    order_number: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationList(SQLModel):
    unread: int
    items: list[NotificationRead]


@router.get("", response_model=NotificationList)
async def my_notifications(user: CurrentUser, session: SessionDep,
                           limit: Annotated[int, Query(ge=1, le=100)] = 30):
    return NotificationList(unread=await inbox.unread_count(session, user),
                            items=await inbox.latest(session, user, limit))


@router.post("/read-all", status_code=204)
async def read_all(user: CurrentUser, session: SessionDep):
    await inbox.mark_all_read(session, user)


@router.post("/{notification_id}/read", status_code=204)
async def read_one(notification_id: uuid.UUID, user: CurrentUser, session: SessionDep):
    if not await inbox.mark_read(session, user, notification_id):
        raise NotFound("Notification not found")
