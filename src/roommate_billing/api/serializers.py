"""API 响应序列化（金额保持整数分）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import (
    AgentConversation,
    AgentMessage,
    AuditLog,
    Bill,
    BillAllocation,
    BillingPeriod,
    HouseholdInvite,
    HouseholdMember,
    Payment,
    PendingAction,
    Person,
    RuleVersion,
    Settlement,
    SettlementLine,
    User,
)
from ..services import rules


def person_payload(person: Person) -> dict[str, Any]:
    return {
        "id": str(person.id),
        "display_name": person.display_name,
        "slug": person.slug,
        "is_active": person.is_active,
        "version": person.version,
    }


def period_payload(period: BillingPeriod) -> dict[str, Any]:
    return {
        "id": str(period.id),
        "period_key": period.period_key,
        "starts_on": period.starts_on.isoformat(),
        "ends_on": period.ends_on.isoformat(),
        "status": period.status,
        "version": period.version,
    }


def allocation_payload(row: BillAllocation) -> dict[str, Any]:
    return {
        "person_id": str(row.person_id),
        "weight_units": row.weight_units,
        "base_cents": row.base_cents,
        "remainder_cents": row.remainder_cents,
        "amount_cents": row.amount_cents,
        "is_remainder_owner": row.is_remainder_owner,
    }


def bill_payload(session: Session, bill: Bill) -> dict[str, Any]:
    allocations = session.scalars(
        select(BillAllocation)
        .join(Person, Person.id == BillAllocation.person_id)
        .where(BillAllocation.bill_id == bill.id)
        .order_by(Person.slug, Person.id)
    ).all()
    return {
        "id": str(bill.id),
        "period_id": str(bill.period_id),
        "category": bill.category,
        "name": bill.name,
        "amount_cents": bill.amount_cents,
        "incurred_on": bill.incurred_on.isoformat() if bill.incurred_on else None,
        "status": bill.status,
        "version": bill.version,
        "void_reason": bill.void_reason,
        "allocations": [allocation_payload(row) for row in allocations],
    }


def payment_payload(payment: Payment) -> dict[str, Any]:
    return {
        "id": str(payment.id),
        "period_id": str(payment.period_id),
        "person_id": str(payment.person_id),
        "amount_cents": payment.amount_cents,
        "kind": payment.kind,
        "method": payment.method,
        "paid_on": payment.paid_on.isoformat(),
        "reference": payment.reference,
        "note": payment.note,
        "adjusts_payment_id": str(payment.adjusts_payment_id)
        if payment.adjusts_payment_id
        else None,
    }


def rule_payload(session: Session, rule: RuleVersion) -> dict[str, Any]:
    data = rules.snapshot(session, rule)
    data["id"] = str(rule.id)
    data["status"] = rule.status
    data["row_version"] = rule.row_version
    data["preview_hash"] = rule.preview_hash
    data["previewed_at"] = rule.previewed_at.isoformat() if rule.previewed_at else None
    data["note"] = rule.note
    return data


def settlement_payload(
    settlement: Settlement, lines: list[SettlementLine] | None = None
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(settlement.id),
        "period_id": str(settlement.period_id),
        "revision": settlement.revision,
        "status": settlement.status,
        "rule_version_id": str(settlement.rule_version_id),
        "bills_total_cents": settlement.bills_total_cents,
        "payments_total_cents": settlement.payments_total_cents,
        "balance_total_cents": settlement.balance_total_cents,
        "created_at": settlement.created_at.isoformat(),
        "supersedes_id": str(settlement.supersedes_id) if settlement.supersedes_id else None,
        "note": settlement.note,
    }
    if lines is not None:
        data["lines"] = [
            {
                "person_id": str(line.person_id),
                "allocated_cents": line.allocated_cents,
                "paid_cents": line.paid_cents,
                "balance_cents": line.balance_cents,
                "remainder_cents": line.remainder_cents,
            }
            for line in lines
        ]
    return data


def settlement_line_payload(line: SettlementLine) -> dict[str, Any]:
    return {
        "person_id": str(line.person_id),
        "allocated_cents": line.allocated_cents,
        "paid_cents": line.paid_cents,
        "balance_cents": line.balance_cents,
        "remainder_cents": line.remainder_cents,
    }


def member_payload(member: HouseholdMember, user: User) -> dict[str, Any]:
    return {
        "user_id": str(member.user_id),
        "email": user.email,
        "display_name": user.display_name,
        "role": member.role,
        "status": member.status,
        "joined_at": member.joined_at.isoformat(),
    }


def invite_payload(invite: HouseholdInvite) -> dict[str, Any]:
    return {
        "id": str(invite.id),
        "role": invite.role,
        "email": invite.email,
        "expires_at": invite.expires_at.isoformat(),
        "created_at": invite.created_at.isoformat(),
    }


def audit_payload(entry: AuditLog) -> dict[str, Any]:
    return {
        "id": entry.id,
        "actor_user_id": str(entry.actor_user_id) if entry.actor_user_id else None,
        "action": entry.action,
        "entity_type": entry.entity_type,
        "entity_id": str(entry.entity_id) if entry.entity_id else None,
        "before": entry.before,
        "after": entry.after,
        "metadata": entry.meta,
        "request_id": str(entry.request_id) if entry.request_id else None,
        "created_at": entry.created_at.isoformat(),
    }


def conversation_payload(conversation: AgentConversation) -> dict[str, Any]:
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
        "archived_at": conversation.archived_at.isoformat() if conversation.archived_at else None,
    }


def agent_message_payload(message: AgentMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
    }


def pending_action_payload(action: PendingAction) -> dict[str, Any]:
    return {
        "id": str(action.id),
        "action_type": action.action_type,
        "preview": action.preview,
        "payload_hash": action.payload_hash,
        "status": action.status,
        "expires_at": action.expires_at.isoformat(),
        "created_at": action.created_at.isoformat(),
        "result": action.result,
    }
