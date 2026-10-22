"""待确认动作的查询、确认与取消。"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import PendingAction
from ..security.principal import Principal
from ..services import bills, payments, periods, rules, settlements
from ..services.audit import jsonable, record_audit
from ..services.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError


def get_action(
    session: Session, *, household_id: UUID, action_id: UUID, principal: Principal
) -> PendingAction:
    action = session.scalar(
        select(PendingAction).where(
            PendingAction.id == action_id,
            PendingAction.household_id == household_id,
        )
    )
    if action is None:
        raise NotFoundError("待确认动作不存在")
    if action.requested_by != principal.user_id and principal.role_for(household_id) not in {
        "owner",
        "admin",
    }:
        raise NotFoundError("待确认动作不存在")
    return action


def confirm_action(
    session: Session,
    *,
    household_id: UUID,
    action_id: UUID,
    principal: Principal,
    expected_payload_hash: str,
    request_id: UUID,
) -> tuple[str, dict[str, Any]]:
    action = session.scalar(
        select(PendingAction)
        .where(
            PendingAction.id == action_id,
            PendingAction.household_id == household_id,
        )
        .with_for_update()
    )
    if action is None:
        raise NotFoundError("待确认动作不存在")
    if action.requested_by != principal.user_id and principal.role_for(household_id) not in {
        "owner",
        "admin",
    }:
        raise ForbiddenError("无权确认该动作")
    if action.payload_hash != expected_payload_hash:
        raise ConflictError("动作内容已变化，请重新预览", code="ACTION_HASH_MISMATCH")
    if action.status == "confirmed":
        return action.action_type, action.result or {}
    if action.status == "cancelled":
        raise ConflictError("动作已取消", code="ACTION_CONSUMED")
    if action.status == "expired" or action.expires_at <= utcnow():
        raise ConflictError("动作已过期，请重新预览", code="ACTION_EXPIRED")
    if action.status != "pending":
        raise ConflictError("动作状态不可确认", code="ACTION_CONSUMED")

    payload = action.payload
    role = principal.role_for(household_id)
    actor = principal.user_id
    action_type = action.action_type
    high_privilege_types = {
        "create_bill",
        "update_bill",
        "void_bill",
        "set_occupancies",
        "create_settlement",
        "confirm_rule_change",
    }
    if action_type in high_privilege_types and role not in {"owner", "admin"}:
        raise ForbiddenError("需要管理员权限")
    result: dict[str, Any]

    if action_type == "create_bill":
        bill = bills.create_bill(
            session,
            household_id=household_id,
            period_id=UUID(payload["period_id"]),
            actor_user_id=actor,
            category=payload["category"],
            name=payload["name"],
            amount_cents=int(payload["amount_cents"]),
            incurred_on=_date_or_none(payload.get("incurred_on")),
            request_id=request_id,
        )
        result = {"bill_id": str(bill.id), "version": bill.version}
    elif action_type == "update_bill":
        fields = payload.get("fields", {})
        bill = bills.update_bill(
            session,
            household_id=household_id,
            bill_id=UUID(payload["bill_id"]),
            actor_user_id=actor,
            expected_version=int(payload["expected_version"]),
            name=fields.get("name"),
            amount_cents=fields.get("amount_cents"),
            incurred_on=_date_or_none(fields.get("incurred_on")),
            request_id=request_id,
        )
        result = {"bill_id": str(bill.id), "version": bill.version}
    elif action_type == "void_bill":
        bill = bills.void_bill(
            session,
            household_id=household_id,
            bill_id=UUID(payload["bill_id"]),
            actor_user_id=actor,
            expected_version=int(payload["expected_version"]),
            reason=payload["reason"],
            request_id=request_id,
        )
        result = {"bill_id": str(bill.id), "status": bill.status}
    elif action_type == "set_occupancies":
        period = periods.set_occupancies(
            session,
            household_id=household_id,
            period_id=UUID(payload["period_id"]),
            actor_user_id=actor,
            items=[
                {"person_id": UUID(item["person_id"]), "days": int(item["days"])}
                for item in payload["items"]
            ],
            expected_version=int(payload["expected_version"]),
            request_id=request_id,
        )
        result = {"period_id": str(period.id), "version": period.version}
    elif action_type == "record_payment":
        person_id = UUID(payload["person_id"])
        if role == "member" and principal.person_for(household_id) != person_id:
            raise ForbiddenError("普通成员只能登记自己的付款")
        payment = payments.record_payment(
            session,
            household_id=household_id,
            period_id=UUID(payload["period_id"]),
            actor_user_id=actor,
            person_id=person_id,
            amount_cents=int(payload["amount_cents"]),
            paid_on=date.fromisoformat(payload["paid_on"]),
            method=payload.get("method", "other"),
            reference=payload.get("reference"),
            note=payload.get("note"),
            request_id=request_id,
        )
        result = {"payment_id": str(payment.id)}
    elif action_type == "create_settlement":
        settlement, lines = settlements.create_settlement(
            session,
            household_id=household_id,
            period_id=UUID(payload["period_id"]),
            actor_user_id=actor,
            expected_period_version=int(payload["expected_period_version"]),
            expected_preview_hash=payload["preview_hash"],
            note=payload.get("note"),
            request_id=request_id,
        )
        result = {
            "settlement_id": str(settlement.id),
            "revision": settlement.revision,
            "line_count": len(lines),
        }
    elif action_type == "confirm_rule_change":
        rule = rules.activate_rule(
            session,
            household_id=household_id,
            rule_version_id=UUID(payload["rule_version_id"]),
            expected_active_version_no=int(payload["expected_active_version_no"]),
            expected_preview_hash=payload["expected_preview_hash"],
            expected_row_version=int(payload["expected_row_version"]),
            actor_user_id=actor,
            request_id=request_id,
        )
        result = {"rule_version_id": str(rule.id), "version_no": rule.version_no}
    else:
        raise ValidationError("未知动作类型")

    action.status = "confirmed"
    action.confirmed_at = utcnow()
    action.consumed_at = utcnow()
    action.result = jsonable(result)
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor,
        action="agent.action_confirm",
        entity_type="pending_action",
        entity_id=action.id,
        before={"action_type": action_type, "status": "pending"},
        after={"action_type": action_type, "status": "confirmed", "result": result},
        request_id=request_id,
    )
    return action_type, action.result or {}


def cancel_action(
    session: Session,
    *,
    household_id: UUID,
    action_id: UUID,
    principal: Principal,
    request_id: UUID,
) -> PendingAction:
    action = get_action(
        session, household_id=household_id, action_id=action_id, principal=principal
    )
    if action.status == "confirmed":
        raise ConflictError("动作已确认", code="ACTION_CONSUMED")
    if action.status == "pending":
        action.status = "cancelled"
        action.consumed_at = utcnow()
        session.flush()
        record_audit(
            session,
            household_id=household_id,
            actor_user_id=principal.user_id,
            action="agent.action_cancel",
            entity_type="pending_action",
            entity_id=action.id,
            request_id=request_id,
        )
    return action


def _date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValidationError("日期格式必须为 YYYY-MM-DD") from exc
