"""Admin audit trail. Call these BEFORE the commit so the entry is saved in the same
transaction as the change (both happen, or neither)."""
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.audit_log import AuditLog
from app.models.user import User


def snapshot(obj: SQLModel, fields: list[str] | None = None) -> dict[str, Any]:
    """Current column values (JSON-safe), to diff against after an update."""
    data = obj.model_dump(include=set(fields) if fields else None)
    data.pop("password_hash", None)
    return jsonable_encoder(data)


def diff(before: dict[str, Any], obj: SQLModel) -> dict[str, list]:
    after = snapshot(obj, list(before))
    return {k: [before[k], after[k]] for k in before if before[k] != after[k]}


def record(
    session: AsyncSession, actor: User, action: str, obj: SQLModel | None = None, *,
    changes: dict | None = None, entity_type: str | None = None, entity_id: Any = None,
) -> None:
    session.add(AuditLog(
        actor_id=actor.id,
        action=action,
        entity_type=entity_type or action.split(".")[0],
        entity_id=str(entity_id if entity_id is not None else obj.id),
        changes=changes,
    ))
