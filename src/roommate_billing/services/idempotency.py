"""幂等写操作支持。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import IdempotencyKey
from .errors import ConflictError


def request_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def execute_idempotent(
    session: Session,
    *,
    actor_user_id: UUID,
    household_id: UUID,
    scope: str,
    key: str,
    payload: dict[str, Any],
    action: Callable[[], tuple[int, dict[str, Any]]],
    ttl_hours: int = 24,
) -> tuple[int, dict[str, Any]]:
    """执行写操作并按 (actor, household, scope, key) 去重。

    action 返回 ``(status_code, response_body)``；response_body 必须是 JSON 可序列化。
    """
    if not key or len(key) > 100:
        raise ConflictError("缺少或非法 Idempotency-Key", code="IDEMPOTENCY_KEY_REQUIRED")
    digest = request_hash(payload)
    existing = session.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.actor_user_id == actor_user_id,
            IdempotencyKey.household_id == household_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
    )
    if existing is not None:
        if existing.request_hash != digest:
            raise ConflictError(
                "同一 Idempotency-Key 被用于不同请求", code="IDEMPOTENCY_KEY_REUSED"
            )
        if existing.status == "completed":
            return existing.response_code or 200, existing.response_body or {}
        raise ConflictError("相同请求正在处理中", code="REQUEST_IN_PROGRESS")

    record = IdempotencyKey(
        actor_user_id=actor_user_id,
        household_id=household_id,
        scope=scope,
        key=key,
        request_hash=digest,
        status="in_progress",
        expires_at=utcnow() + timedelta(hours=ttl_hours),
    )
    session.add(record)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        raise ConflictError("相同请求正在处理中", code="REQUEST_IN_PROGRESS") from exc

    status_code, body = action()
    record.status = "completed"
    record.response_code = status_code
    record.response_body = body
    session.flush()
    return status_code, body
