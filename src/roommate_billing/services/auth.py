"""登录、会话、邀请与成员角色服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db.base import utcnow
from ..db.models import AuthSession, Household, HouseholdInvite, HouseholdMember, Person, User
from ..security.passwords import (
    hash_password,
    hmac_hex,
    new_token,
    secure_compare,
    sha256_hex,
    verify_password,
)
from ..security.principal import Principal
from .audit import record_audit
from .errors import (
    AccountLockedError,
    ConflictError,
    ForbiddenError,
    InvalidCredentialsError,
    UnauthorizedError,
    ValidationError,
)

LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_MINUTES = 15
INVITE_TTL_HOURS = 168


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User
    principal: Principal
    session_token: str
    csrf_token: str


def _normalize_email(email: str) -> str:
    value = email.strip().lower()
    if not value or len(value) > 320 or "@" not in value:
        raise ValidationError("邮箱格式非法")
    return value


def _create_session(
    db: Session,
    *,
    user_id: UUID,
    user_agent: str | None,
    ip_hash: str | None,
    now,
) -> tuple[AuthSession, str, str]:
    settings = get_settings()
    session_token = new_token()
    csrf_token = new_token()
    auth_session = AuthSession(
        user_id=user_id,
        token_hash=sha256_hex(session_token),
        csrf_hash=hmac_hex(csrf_token),
        last_seen_at=now,
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        ip_hash=ip_hash,
        user_agent=(user_agent or "")[:512] or None,
    )
    db.add(auth_session)
    db.flush()
    return auth_session, session_token, csrf_token


def _memberships(
    db: Session, user_id: UUID, requested_household_id: UUID | None
) -> tuple[dict[UUID, str], dict[UUID, UUID | None], UUID | None, str | None, UUID | None]:
    rows = db.execute(
        select(HouseholdMember, Household)
        .join(Household, Household.id == HouseholdMember.household_id)
        .where(
            HouseholdMember.user_id == user_id,
            HouseholdMember.status == "active",
            Household.status == "active",
        )
        .order_by(Household.created_at, Household.id)
    ).all()
    memberships = {member.household_id: member.role for member, _household in rows}
    if not memberships:
        return {}, {}, None, None, None

    person_rows = db.scalars(
        select(Person).where(
            Person.user_id == user_id,
            Person.household_id.in_(memberships),
            Person.is_active.is_(True),
        )
    )
    person_ids = {person.household_id: person.id for person in person_rows}

    active = (
        requested_household_id if requested_household_id in memberships else next(iter(memberships))
    )
    return memberships, person_ids, active, memberships[active], person_ids.get(active)


def build_principal(
    db: Session,
    *,
    user_id: UUID,
    session_id: UUID,
    requested_household_id: UUID | None = None,
) -> Principal:
    memberships, person_ids, active, role, person_id = _memberships(
        db, user_id, requested_household_id
    )
    return Principal(
        user_id=user_id,
        household_id=active,
        role=role,
        person_id=person_id,
        memberships=memberships,
        person_ids=person_ids,
        session_id=session_id,
    )


def authenticate_session(
    db: Session,
    *,
    token: str | None,
    csrf_token: str | None,
    csrf_cookie_token: str | None,
    require_csrf: bool,
    requested_household_id: UUID | None = None,
) -> Principal:
    if not token:
        raise UnauthorizedError("需要登录", code="AUTH_REQUIRED")
    auth_session = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256_hex(token)))
    now = utcnow()
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= now
    ):
        raise UnauthorizedError("会话已失效，请重新登录", code="AUTH_REQUIRED")
    settings = get_settings()
    if auth_session.last_seen_at + timedelta(hours=settings.session_idle_hours) <= now:
        auth_session.revoked_at = now
        db.flush()
        raise UnauthorizedError("会话空闲超时，请重新登录", code="AUTH_REQUIRED")
    if require_csrf and (
        not csrf_token
        or not csrf_cookie_token
        or not secure_compare(csrf_token, csrf_cookie_token)
        or not secure_compare(hmac_hex(csrf_token), auth_session.csrf_hash)
    ):
        raise ForbiddenError("CSRF 校验失败", code="CSRF_INVALID")
    user = db.get(User, auth_session.user_id)
    if user is None or not user.is_active:
        auth_session.revoked_at = now
        db.flush()
        raise UnauthorizedError("账户不可用", code="AUTH_REQUIRED")

    auth_session.last_seen_at = now
    db.flush()
    return build_principal(
        db,
        user_id=user.id,
        session_id=auth_session.id,
        requested_household_id=requested_household_id,
    )


def login(
    db: Session,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
    ip_hash: str | None = None,
) -> LoginResult:
    normalized = _normalize_email(email)
    user = db.scalar(select(User).where(User.email == normalized))
    now = utcnow()
    if user is None:
        verify_password(password, None)
        record_audit(
            db,
            household_id=None,
            actor_user_id=None,
            action="auth.login_failed",
            entity_type="user",
            entity_id=None,
            after={"reason": "unknown_email"},
        )
        raise InvalidCredentialsError("邮箱或密码错误", code="INVALID_CREDENTIALS")
    if user.locked_until is not None and user.locked_until > now:
        raise AccountLockedError("登录失败次数过多，请稍后再试", code="ACCOUNT_LOCKED")

    if not user.is_active or not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= LOGIN_MAX_FAILURES:
            user.locked_until = now + timedelta(minutes=LOGIN_LOCK_MINUTES)
            user.failed_login_count = 0
        record_audit(
            db,
            household_id=None,
            actor_user_id=user.id,
            action="auth.login_failed",
            entity_type="user",
            entity_id=user.id,
            after={"failed_login_count": user.failed_login_count},
        )
        raise InvalidCredentialsError("邮箱或密码错误", code="INVALID_CREDENTIALS")

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    auth_session, session_token, csrf_token = _create_session(
        db,
        user_id=user.id,
        user_agent=user_agent,
        ip_hash=ip_hash,
        now=now,
    )
    principal = build_principal(db, user_id=user.id, session_id=auth_session.id)
    record_audit(
        db,
        household_id=principal.household_id,
        actor_user_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        after={"session_id": str(auth_session.id)},
    )
    return LoginResult(
        user=user,
        principal=principal,
        session_token=session_token,
        csrf_token=csrf_token,
    )


def logout(db: Session, principal: Principal) -> None:
    if principal.session_id is None:
        return
    auth_session = db.get(AuthSession, principal.session_id)
    if auth_session is not None and auth_session.revoked_at is None:
        auth_session.revoked_at = utcnow()
        db.flush()
        record_audit(
            db,
            household_id=principal.household_id,
            actor_user_id=principal.user_id,
            action="auth.logout",
            entity_type="auth_session",
            entity_id=auth_session.id,
        )


def rotate_csrf(db: Session, principal: Principal) -> str:
    if principal.session_id is None:
        raise UnauthorizedError("需要登录", code="AUTH_REQUIRED")
    auth_session = db.get(AuthSession, principal.session_id)
    if auth_session is None or auth_session.revoked_at is not None:
        raise UnauthorizedError("会话已失效", code="AUTH_REQUIRED")
    token = new_token()
    auth_session.csrf_hash = hmac_hex(token)
    db.flush()
    return token


def change_password(
    db: Session,
    *,
    principal: Principal,
    current_password: str,
    new_password: str,
) -> None:
    user = db.get(User, principal.user_id)
    if user is None or not verify_password(current_password, user.password_hash):
        raise InvalidCredentialsError("当前密码错误", code="INVALID_CREDENTIALS")
    try:
        user.password_hash = hash_password(new_password)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    user.password_changed_at = utcnow()
    sessions = db.scalars(
        select(AuthSession).where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.id != principal.session_id,
        )
    )
    now = utcnow()
    for auth_session in sessions:
        auth_session.revoked_at = now
    db.flush()
    record_audit(
        db,
        household_id=principal.household_id,
        actor_user_id=user.id,
        action="auth.password_change",
        entity_type="user",
        entity_id=user.id,
    )


def register(
    db: Session,
    *,
    email: str,
    password: str,
    display_name: str,
) -> User:
    if not get_settings().allow_registration:
        raise ForbiddenError("当前未开放注册", code="REGISTRATION_DISABLED")
    normalized = _normalize_email(email)
    if not 1 <= len(display_name) <= 80:
        raise ValidationError("显示名长度必须为 1–80")
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    user = User(
        email=normalized,
        display_name=display_name.strip(),
        password_hash=password_hash,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("邮箱已注册") from exc
    record_audit(
        db,
        household_id=None,
        actor_user_id=user.id,
        action="auth.register",
        entity_type="user",
        entity_id=user.id,
        after={"email": normalized},
    )
    return user


def list_user_households(db: Session, user_id: UUID) -> list[dict]:
    rows = db.execute(
        select(HouseholdMember, Household)
        .join(Household, Household.id == HouseholdMember.household_id)
        .where(
            HouseholdMember.user_id == user_id,
            HouseholdMember.status == "active",
            Household.status == "active",
        )
        .order_by(Household.created_at, Household.id)
    ).all()
    person_rows = db.scalars(
        select(Person).where(
            Person.user_id == user_id,
            Person.household_id.in_([household.id for _member, household in rows]),
            Person.is_active.is_(True),
        )
    )
    person_ids = {person.household_id: person.id for person in person_rows}
    return [
        {
            "id": str(household.id),
            "name": household.name,
            "role": member.role,
            "person_id": str(person_ids[household.id]) if household.id in person_ids else None,
        }
        for member, household in rows
    ]


def create_invite(
    db: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    role: str,
    email: str | None = None,
) -> tuple[HouseholdInvite, str]:
    if role not in {"admin", "member"}:
        raise ValidationError("邀请角色只能是 admin 或 member")
    normalized_email = _normalize_email(email) if email else None
    token = new_token()
    invite = HouseholdInvite(
        household_id=household_id,
        email=normalized_email,
        role=role,
        token_hash=sha256_hex(token),
        expires_at=utcnow() + timedelta(hours=INVITE_TTL_HOURS),
        created_by=actor_user_id,
    )
    db.add(invite)
    db.flush()
    record_audit(
        db,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="invite.create",
        entity_type="household_invite",
        entity_id=invite.id,
        after={"role": role, "email": normalized_email},
    )
    return invite, token


def list_invites(db: Session, household_id: UUID) -> list[HouseholdInvite]:
    now = utcnow()
    return list(
        db.scalars(
            select(HouseholdInvite)
            .where(
                HouseholdInvite.household_id == household_id,
                HouseholdInvite.accepted_at.is_(None),
                HouseholdInvite.expires_at > now,
            )
            .order_by(HouseholdInvite.created_at.desc())
        )
    )


def accept_invite(db: Session, *, principal: Principal, token: str) -> HouseholdMember:
    invite = db.scalar(
        select(HouseholdInvite).where(HouseholdInvite.token_hash == sha256_hex(token))
    )
    now = utcnow()
    if invite is None or invite.accepted_at is not None or invite.expires_at <= now:
        raise ValidationError("邀请无效或已过期")
    user = db.get(User, principal.user_id)
    if user is None:
        raise UnauthorizedError("需要登录", code="AUTH_REQUIRED")
    if invite.email is not None and invite.email != user.email:
        raise ForbiddenError("邀请邮箱与当前账户不一致")
    existing = db.get(HouseholdMember, (invite.household_id, user.id))
    if existing is not None and existing.status == "active":
        raise ConflictError("已经是该账本成员")
    if existing is None:
        membership = HouseholdMember(
            household_id=invite.household_id,
            user_id=user.id,
            role=invite.role,
            status="active",
        )
        db.add(membership)
    else:
        existing.role = invite.role
        existing.status = "active"
        existing.left_at = None
        membership = existing
    invite.accepted_by = user.id
    invite.accepted_at = now
    db.flush()
    record_audit(
        db,
        household_id=invite.household_id,
        actor_user_id=user.id,
        action="invite.accept",
        entity_type="household_invite",
        entity_id=invite.id,
        after={"role": invite.role},
    )
    return membership


def list_members(db: Session, household_id: UUID) -> list[tuple[HouseholdMember, User]]:
    return list(
        db.execute(
            select(HouseholdMember, User)
            .join(User, User.id == HouseholdMember.user_id)
            .where(HouseholdMember.household_id == household_id)
            .order_by(HouseholdMember.joined_at)
        ).all()
    )


def update_member(
    db: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    target_user_id: UUID,
    role: str | None,
    status: str | None,
) -> HouseholdMember:
    actor = db.get(HouseholdMember, (household_id, actor_user_id))
    if actor is None or actor.role != "owner" or actor.status != "active":
        raise ForbiddenError("只有账本 owner 可以修改成员")
    target = db.get(HouseholdMember, (household_id, target_user_id))
    if target is None:
        raise ValidationError("成员不存在")
    if role is not None and role not in {"admin", "member"}:
        raise ValidationError("角色只能是 admin 或 member")
    if status is not None and status not in {"active", "left"}:
        raise ValidationError("状态只能是 active 或 left")
    if target.role == "owner":
        raise ForbiddenError("不能在这里修改 owner；请使用所有权转移流程")
    before = {"role": target.role, "status": target.status}
    if role is not None:
        target.role = role
    if status is not None:
        target.status = status
        target.left_at = utcnow() if status == "left" else None
    db.flush()
    record_audit(
        db,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="member.update",
        entity_type="household_member",
        entity_id=target.user_id,
        before=before,
        after={"role": target.role, "status": target.status},
    )
    return target
