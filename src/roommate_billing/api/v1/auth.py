"""认证 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from ...config import get_settings
from ...db.models import User
from ...schemas.api import (
    ChangePasswordRequest,
    InviteAccept,
    LoginRequest,
    RegisterRequest,
)
from ...security.cookies import clear_auth_cookies, set_auth_cookies
from ...services import auth
from ...services.errors import ForbiddenError, InvalidCredentialsError
from ..deps import (
    Principal,
    client_ip_hash,
    get_current_principal,
    get_db,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])


def _check_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    if not origin:
        return
    allowed = get_settings().app_base_url.rstrip("/")
    if origin.rstrip("/") != allowed:
        raise ForbiddenError("请求来源不被允许", code="ORIGIN_INVALID")


def _user_payload(user) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
    }


@router.post("/auth/login")
def login(
    request: Request,
    body: LoginRequest,
    response: Response,
    session: Session = Depends(get_db),
) -> dict:
    _check_origin(request)
    try:
        result = auth.login(
            session,
            email=body.email,
            password=body.password,
            user_agent=request.headers.get("User-Agent"),
            ip_hash=client_ip_hash(request),
        )
    except InvalidCredentialsError:
        # 失败次数/审计必须落库；否则事务回滚会丢失安全事件。
        session.commit()
        raise
    set_auth_cookies(
        response,
        settings=get_settings(),
        session_token=result.session_token,
        csrf_token=result.csrf_token,
    )
    return {
        "data": {
            "user": _user_payload(result.user),
            "households": auth.list_user_households(session, result.user.id),
            "csrf_token": result.csrf_token,
        }
    }


@router.post("/auth/register", status_code=201)
def register(
    request: Request,
    body: RegisterRequest,
    response: Response,
    session: Session = Depends(get_db),
) -> dict:
    _check_origin(request)
    user = auth.register(
        session,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
    )
    result = auth.login(
        session,
        email=user.email,
        password=body.password,
        user_agent=request.headers.get("User-Agent"),
        ip_hash=client_ip_hash(request),
    )
    set_auth_cookies(
        response,
        settings=get_settings(),
        session_token=result.session_token,
        csrf_token=result.csrf_token,
    )
    return {
        "data": {
            "user": _user_payload(user),
            "households": auth.list_user_households(session, user.id),
            "csrf_token": result.csrf_token,
        }
    }


@router.post("/auth/logout", status_code=204)
def logout(
    response: Response,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> Response:
    auth.logout(session, principal)
    clear_auth_cookies(response, settings=get_settings())
    response.status_code = 204
    return response


@router.get("/auth/me")
def me(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    user = session.get(User, principal.user_id)
    if user is None:
        raise InvalidCredentialsError("账户不存在", code="AUTH_REQUIRED")
    return {
        "data": {
            "user": _user_payload(user),
            "households": auth.list_user_households(session, user.id),
            "active_household_id": str(principal.household_id) if principal.household_id else None,
        }
    }


@router.get("/auth/csrf")
def csrf(
    response: Response,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    token = auth.rotate_csrf(session, principal)
    settings = get_settings()
    response.set_cookie(
        "rba_csrf",
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"data": {"csrf_token": token}}


@router.post("/auth/password", status_code=204)
def change_password(
    body: ChangePasswordRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> None:
    auth.change_password(
        session,
        principal=principal,
        current_password=body.current_password,
        new_password=body.new_password,
    )


@router.post("/auth/invites/accept")
def accept_invite(
    body: InviteAccept,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    membership = auth.accept_invite(session, principal=principal, token=body.token)
    return {
        "data": {
            "household_id": str(membership.household_id),
            "role": membership.role,
        }
    }
