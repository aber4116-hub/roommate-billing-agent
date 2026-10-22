"""API 依赖：数据库、当前主体、权限与请求 ID。"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from ..agent.providers import build_provider
from ..config import get_settings
from ..db.session import get_db
from ..security.principal import Principal
from ..services import auth
from ..services.errors import ConflictError, ForbiddenError, NotFoundError

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_current_principal(request: Request, session: Session = Depends(get_db)) -> Principal:
    settings = get_settings()
    requested: UUID | None = None
    raw_household = request.headers.get("X-Household-ID")
    if raw_household:
        try:
            requested = UUID(raw_household)
        except ValueError:
            requested = None
    return auth.authenticate_session(
        session,
        token=request.cookies.get(settings.session_cookie_name),
        csrf_token=request.headers.get("X-CSRF-Token"),
        csrf_cookie_token=request.cookies.get("rba_csrf"),
        require_csrf=request.method not in SAFE_METHODS,
        requested_household_id=requested,
    )


def ensure_household(principal: Principal, household_id: UUID) -> None:
    if household_id == principal.household_id or household_id in principal.memberships:
        return
    # 不泄露另一个账本是否存在。
    raise NotFoundError("账本不存在")


def require_admin(principal: Principal, household_id: UUID | None = None) -> None:
    role = principal.role_for(household_id) if household_id else principal.role
    if role not in {"owner", "admin"}:
        raise ForbiddenError("需要管理员权限")


def get_request_id(request: Request) -> UUID:
    state_value = getattr(request.state, "request_id", None)
    if isinstance(state_value, UUID):
        return state_value
    header = request.headers.get("X-Request-ID")
    if header:
        try:
            return UUID(header)
        except ValueError:
            pass
    return uuid4()


def client_ip_hash(request: Request) -> str:
    from ..security.passwords import hmac_hex

    forwarded = request.headers.get("X-Forwarded-For", "")
    client = forwarded.split(",", 1)[0].strip() if forwarded else ""
    if not client and request.client is not None:
        client = request.client.host
    return hmac_hex(client or "unknown")


def require_idempotency_key(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> str:
    if not idempotency_key:
        raise ConflictError("财务写操作必须提供 Idempotency-Key", code="IDEMPOTENCY_KEY_REQUIRED")
    return idempotency_key


def get_llm_provider():
    return build_provider(get_settings())


__all__ = [
    "Principal",
    "client_ip_hash",
    "ensure_household",
    "get_current_principal",
    "get_db",
    "get_llm_provider",
    "get_request_id",
    "require_admin",
    "require_idempotency_key",
]
