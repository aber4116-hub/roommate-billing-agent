"""Agent 写工具的待确认动作执行分支。"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from roommate_billing.agent.tools import ToolGateway
from roommate_billing.agent.types import ToolCall
from roommate_billing.db.models import Payment, PendingAction
from roommate_billing.services import actions, bills, periods


def _hash(db_session, result) -> str:
    action = db_session.get(PendingAction, UUID(result["pending_action_id"]))
    assert action is not None
    return action.payload_hash


def test_update_void_occupancies_and_payment_actions(
    seed, owner_principal, db_session: Session
) -> None:
    gateway = ToolGateway(db_session, owner_principal)
    bill = bills.list_bills(db_session, seed.household_id, seed.period_id)[0]
    updated = gateway.execute(
        ToolCall(
            id="update",
            name="update_bill",
            arguments={
                "bill_id": str(bill.id),
                "fields": {"amount_cents": 12345},
                "expected_version": bill.version,
            },
        )
    )
    assert updated["ok"] is True, updated
    actions.confirm_action(
        db_session,
        household_id=seed.household_id,
        action_id=UUID(updated["pending_action_id"]),
        principal=owner_principal,
        expected_payload_hash=_hash(db_session, updated),
        request_id=uuid4(),
    )
    db_session.refresh(bill)
    assert bill.amount_cents == 12345

    voided = gateway.execute(
        ToolCall(
            id="void",
            name="void_bill",
            arguments={
                "bill_id": str(bill.id),
                "reason": "测试作废",
                "expected_version": bill.version,
            },
        )
    )
    assert voided["ok"] is True, voided
    actions.confirm_action(
        db_session,
        household_id=seed.household_id,
        action_id=UUID(voided["pending_action_id"]),
        principal=owner_principal,
        expected_payload_hash=_hash(db_session, voided),
        request_id=uuid4(),
    )
    db_session.refresh(bill)
    assert bill.status == "voided"

    period = periods.get_period(db_session, seed.household_id, seed.period_id)
    occupancy = gateway.execute(
        ToolCall(
            id="occ",
            name="set_occupancies",
            arguments={
                "period_key": "2026-10",
                "items": [
                    {"person_slug": "lin", "days": 20},
                    {"person_slug": "zhe", "days": 31},
                    {"person_slug": "zhou", "days": 31},
                ],
                "expected_period_version": period.version,
            },
        )
    )
    assert occupancy["ok"] is True, occupancy
    actions.confirm_action(
        db_session,
        household_id=seed.household_id,
        action_id=UUID(occupancy["pending_action_id"]),
        principal=owner_principal,
        expected_payload_hash=_hash(db_session, occupancy),
        request_id=uuid4(),
    )
    assert periods.occupancy_map(db_session, seed.period_id)[seed.people["lin"]] == 20

    payment = gateway.execute(
        ToolCall(
            id="pay",
            name="record_payment",
            arguments={
                "period_key": "2026-10",
                "person_slug": "lin",
                "amount_cents": 8800,
                "paid_on": "2026-10-23",
                "method": "wechat",
            },
        )
    )
    assert payment["ok"] is True, payment
    actions.confirm_action(
        db_session,
        household_id=seed.household_id,
        action_id=UUID(payment["pending_action_id"]),
        principal=owner_principal,
        expected_payload_hash=_hash(db_session, payment),
        request_id=uuid4(),
    )
    assert (
        db_session.scalar(
            select(Payment).where(Payment.person_id == seed.people["lin"])
        ).amount_cents
        == 8800
    )
