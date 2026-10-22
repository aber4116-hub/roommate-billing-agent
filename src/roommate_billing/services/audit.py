"""审计日志服务。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..db.models import AuditLog


def jsonable(value: Any) -> Any:
    """把 UUID/日期等转换成 JSONB 可写结构；不记录敏感配置。"""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [jsonable(item) for item in value]
    return value


def record_audit(
    session: Session,
    *,
    household_id: UUID | None,
    actor_user_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    request_id: UUID | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditLog:
    entry = AuditLog(
        household_id=household_id,
        actor_user_id=actor_user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=jsonable(before) if before is not None else None,
        after=jsonable(after) if after is not None else None,
        meta=jsonable(meta or {}),
        request_id=request_id,
    )
    session.add(entry)
    return entry
