"""审计日志查询 API（管理员）。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.models import AuditLog
from ..deps import (
    Principal,
    ensure_household,
    get_current_principal,
    get_db,
    require_admin,
)
from ..serializers import audit_payload

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/households/{household_id}/audit-logs")
def list_audit_logs(
    household_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    before_id: int | None = Query(default=None, ge=1),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    statement = (
        select(AuditLog)
        .where(AuditLog.household_id == household_id)
        .order_by(AuditLog.id.desc())
        .limit(limit + 1)
    )
    if before_id is not None:
        statement = statement.where(AuditLog.id < before_id)
    rows = list(session.scalars(statement))
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "data": {
            "items": [audit_payload(row) for row in rows],
            "next_before_id": rows[-1].id if has_more and rows else None,
        }
    }
