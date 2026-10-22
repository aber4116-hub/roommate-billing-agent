"""结算服务集成测试。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from roommate_billing.db.models import Payment, Settlement
from roommate_billing.services import payments, periods, settlements
from roommate_billing.services.errors import ConflictError


def _pay_all(db_session: Session, seed) -> None:
    for slug, amount in (("lin", 11378), ("zhe", 18964), ("zhou", 18963)):
        payments.record_payment(
            db_session,
            household_id=seed.household_id,
            period_id=seed.period_id,
            actor_user_id=seed.user_id,
            person_id=seed.people[slug],
            amount_cents=amount,
            paid_on=date(2026, 10, 5),
            method="bank",
            request_id=uuid4(),
        )
    db_session.commit()


def _lock(db_session: Session, seed) -> None:
    period = periods.get_period(db_session, seed.household_id, seed.period_id)
    periods.lock_period(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        expected_version=period.version,
        request_id=uuid4(),
    )
    db_session.commit()


def _create_settlement(db_session: Session, seed):
    preview = settlements.preview(
        db_session, household_id=seed.household_id, period_id=seed.period_id
    )
    settlement, lines = settlements.create_settlement(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        expected_period_version=preview["period_version"],
        expected_preview_hash=preview["preview_hash"],
        request_id=uuid4(),
    )
    db_session.commit()
    return preview, settlement, lines


def test_preview_and_create_full_settlement(db_session: Session, seed) -> None:
    _pay_all(db_session, seed)
    _lock(db_session, seed)
    preview = settlements.preview(
        db_session, household_id=seed.household_id, period_id=seed.period_id
    )
    assert preview["bills_total_cents"] == 49305
    assert preview["payments_total_cents"] == 49305
    assert preview["balance_total_cents"] == 0
    assert [line["balance_cents"] for line in preview["lines"]] == [1116, -562, -554]
    assert [line["remainder_cents"] for line in preview["lines"]] == [0, 0, 7]

    settlement, lines = settlements.create_settlement(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        expected_period_version=preview["period_version"],
        expected_preview_hash=preview["preview_hash"],
        request_id=uuid4(),
    )
    db_session.commit()
    assert settlement.status == "final"
    assert settlement.revision == 1
    assert sum(line.allocated_cents for line in lines) == 49305
    assert sum(line.paid_cents for line in lines) == 49305
    assert sum(line.balance_cents for line in lines) == 0
    assert periods.get_period(db_session, seed.household_id, seed.period_id).status == "settled"


def test_duplicate_settlement_is_rejected(db_session: Session, seed) -> None:
    _lock(db_session, seed)
    _preview, _settlement, _ = _create_settlement(db_session, seed)
    # 账期已 settled，再次创建需要先重开。
    with pytest.raises(ConflictError) as exc_info:
        _create_settlement(db_session, seed)
    assert exc_info.value.code == "PERIOD_NOT_LOCKED"


def test_stale_preview_is_rejected(db_session: Session, seed) -> None:
    _lock(db_session, seed)
    preview = settlements.preview(
        db_session, household_id=seed.household_id, period_id=seed.period_id
    )
    # 付款变化后旧 preview_hash 必须失效。
    payments.record_payment(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        person_id=seed.people["lin"],
        amount_cents=100,
        paid_on=date(2026, 10, 6),
        method="cash",
        request_id=uuid4(),
    )
    db_session.commit()
    with pytest.raises(ConflictError) as exc_info:
        settlements.create_settlement(
            db_session,
            household_id=seed.household_id,
            period_id=seed.period_id,
            actor_user_id=seed.user_id,
            expected_period_version=preview["period_version"],
            expected_preview_hash=preview["preview_hash"],
            request_id=uuid4(),
        )
    assert exc_info.value.code in {"VERSION_CONFLICT", "SETTLEMENT_PREVIEW_STALE"}


def test_reopen_creates_revision_and_supersedes(db_session: Session, seed) -> None:
    _pay_all(db_session, seed)
    _lock(db_session, seed)
    _preview, first, _ = _create_settlement(db_session, seed)
    period = periods.get_period(db_session, seed.household_id, seed.period_id)
    periods.reopen_period(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        expected_version=period.version,
        reason="补录一笔付款",
        request_id=uuid4(),
    )
    db_session.commit()
    payments.record_payment(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        person_id=seed.people["lin"],
        amount_cents=100,
        paid_on=date(2026, 10, 6),
        method="cash",
        request_id=uuid4(),
    )
    db_session.commit()
    _lock(db_session, seed)
    _preview2, second, _ = _create_settlement(db_session, seed)
    db_session.refresh(first)
    assert first.status == "superseded"
    assert first.superseded_at is not None
    assert second.revision == 2
    assert second.supersedes_id == first.id
    rows = settlements.list_settlements(db_session, seed.household_id, seed.period_id)
    assert [row.revision for row in rows] == [2, 1]
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Settlement)
            .where(Settlement.period_id == seed.period_id, Settlement.status == "final")
        )
        == 1
    )


def test_explain_and_export(db_session: Session, seed) -> None:
    _pay_all(db_session, seed)
    _lock(db_session, seed)
    _preview, settlement, _ = _create_settlement(db_session, seed)
    explanation = settlements.explain(
        db_session,
        household_id=seed.household_id,
        settlement_id=settlement.id,
        person_id=seed.people["lin"],
    )
    assert explanation["allocated_cents"] == 12494
    assert explanation["paid_cents"] == 11378
    assert explanation["balance_cents"] == 1116
    assert len(explanation["components"]) == 4
    assert "¥11.16" in explanation["explanation"]

    filename, csv_text = settlements.export_csv(
        db_session, household_id=seed.household_id, settlement_id=settlement.id
    )
    assert filename.endswith(".csv")
    assert "2026-10" in csv_text
    assert "124.94" in csv_text
    assert "-5.62" in csv_text


def test_settlement_snapshot_keeps_rule_and_bills(db_session: Session, seed) -> None:
    _pay_all(db_session, seed)
    _lock(db_session, seed)
    _preview, settlement, _ = _create_settlement(db_session, seed)
    assert settlement.rule_snapshot["version_no"] == 1
    assert len(settlement.rule_snapshot["items"]) == 5
    assert len(settlement.bills_snapshot["bills"]) == 4
    assert settlement.rule_version_id
    assert settlement.request_id


def test_rule_change_does_not_alter_payment_rows(db_session: Session, seed) -> None:
    from roommate_billing.services import rules

    _pay_all(db_session, seed)
    before = [
        (row.id, row.amount_cents, row.kind)
        for row in db_session.scalars(select(Payment).order_by(Payment.recorded_at))
    ]
    items = [
        {"category": "electricity", "split_method": "days", "fallback_method": "equal_household"},
        {
            "category": "water",
            "split_method": "equal_household",
            "fallback_method": "equal_household",
        },
        {
            "category": "internet",
            "split_method": "equal_household",
            "fallback_method": "equal_household",
        },
        {
            "category": "trash",
            "split_method": "equal_household",
            "fallback_method": "equal_household",
        },
        {
            "category": "other",
            "split_method": "equal_household",
            "fallback_method": "equal_household",
        },
    ]
    draft = rules.create_draft(
        db_session,
        household_id=seed.household_id,
        owner_person_id=seed.people["zhou"],
        items=items,
        note="规则变更不应覆盖实收",
        actor_user_id=seed.user_id,
        request_id=uuid4(),
    )
    draft, _ = rules.preview_rule(
        db_session,
        household_id=seed.household_id,
        rule_version_id=draft.id,
        actor_user_id=seed.user_id,
        request_id=uuid4(),
    )
    db_session.commit()
    rules.activate_rule(
        db_session,
        household_id=seed.household_id,
        rule_version_id=draft.id,
        expected_active_version_no=1,
        expected_preview_hash=draft.preview_hash,
        expected_row_version=1,
        actor_user_id=seed.user_id,
        request_id=uuid4(),
    )
    db_session.commit()
    after = [
        (row.id, row.amount_cents, row.kind)
        for row in db_session.scalars(select(Payment).order_by(Payment.recorded_at))
    ]
    assert after == before


def test_settlement_lines_append_only(db_session: Session, seed) -> None:
    _lock(db_session, seed)
    _preview, _settlement, lines = _create_settlement(db_session, seed)
    from sqlalchemy import update
    from sqlalchemy.exc import DBAPIError

    from roommate_billing.db.models import SettlementLine

    with pytest.raises(DBAPIError):
        db_session.execute(
            update(SettlementLine).where(SettlementLine.id == lines[0].id).values(paid_cents=999)
        )
        db_session.commit()
    db_session.rollback()
