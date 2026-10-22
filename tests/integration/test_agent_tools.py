"""Agent 只读工具与结算查询测试。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from roommate_billing.agent.tools import ToolGateway
from roommate_billing.agent.types import ToolCall
from roommate_billing.services import periods, settlements


def test_read_tools_and_settlement_explain(seed, owner_principal, db_session: Session) -> None:
    gateway = ToolGateway(db_session, owner_principal)
    ledger = gateway.execute(ToolCall(id="1", name="get_current_ledger", arguments={}))
    assert ledger["ok"] is True

    period = gateway.execute(
        ToolCall(
            id="2",
            name="get_billing_period",
            arguments={"period_key": "2026-10"},
        )
    )
    assert period["ok"] is True
    assert len(period["bills"]) == 4

    preview = gateway.execute(
        ToolCall(
            id="3",
            name="preview_split",
            arguments={
                "period_key": "2026-10",
                "bills": [{"category": "electricity", "name": "测试电费", "amount_cents": 10000}],
            },
        )
    )
    assert preview["ok"] is True
    assert sum(item["amount_cents"] for item in preview["bills"]) == 10000

    history = gateway.execute(
        ToolCall(
            id="4",
            name="get_settlement_history",
            arguments={"period_key": "2026-10"},
        )
    )
    assert history["ok"] is True
    assert history["items"] == []

    missing = gateway.execute(
        ToolCall(
            id="8",
            name="record_payment",
            arguments={"period_key": "2026-10", "person_slug": "lin"},
        )
    )
    assert missing["error"]["code"] == "MISSING_ARGUMENT"

    # 锁定并创建正式结算，验证 explain/export 工具。
    to_lock = periods.get_period(db_session, seed.household_id, seed.period_id)
    periods.lock_period(
        db_session,
        household_id=seed.household_id,
        period_id=to_lock.id,
        actor_user_id=seed.user_id,
        expected_version=to_lock.version,
        request_id=uuid4(),
    )
    db_session.commit()
    preview_data = settlements.preview(
        db_session, household_id=seed.household_id, period_id=seed.period_id
    )
    settlement, _lines = settlements.create_settlement(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        expected_period_version=preview_data["period_version"],
        expected_preview_hash=preview_data["preview_hash"],
        request_id=uuid4(),
    )
    db_session.commit()

    explained = gateway.execute(
        ToolCall(
            id="5",
            name="explain_settlement",
            arguments={
                "settlement_id": str(settlement.id),
                "person_slug": "lin",
            },
        )
    )
    assert explained["ok"] is True
    assert "allocated_cents" in explained

    exported = gateway.execute(
        ToolCall(
            id="6",
            name="export_settlement",
            arguments={"settlement_id": str(settlement.id)},
        )
    )
    assert exported["ok"] is True
    assert exported["filename"].endswith(".csv")

    unknown = gateway.execute(ToolCall(id="7", name="confirm_rule_change", arguments={}))
    assert unknown["error"]["code"] == "TOOL_NOT_ALLOWED"
