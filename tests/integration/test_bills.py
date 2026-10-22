"""账单服务集成测试。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from roommate_billing.db.models import AuditLog, Bill, BillAllocation
from roommate_billing.services import bills, periods


def _bill_by_category(session: Session, period_id, category: str) -> Bill:
    return session.scalar(
        select(Bill).where(
            Bill.period_id == period_id,
            Bill.category == category,
            Bill.status == "active",
        )
    )


def test_seed_bill_allocations_conserve(db_session: Session, seed) -> None:
    electricity = _bill_by_category(db_session, seed.period_id, "electricity")
    rows = bills.get_allocations(db_session, seed.household_id, electricity.id)
    assert [row.amount_cents for row in rows] == [6638, 11063, 11064]
    assert sum(row.amount_cents for row in rows) == electricity.amount_cents

    internet = _bill_by_category(db_session, seed.period_id, "internet")
    rows = bills.get_allocations(db_session, seed.household_id, internet.id)
    assert [row.amount_cents for row in rows] == [2966, 2966, 2968]


def test_update_bill_recalculates_allocations(db_session: Session, seed) -> None:
    electricity = _bill_by_category(db_session, seed.period_id, "electricity")
    bills.update_bill(
        db_session,
        household_id=seed.household_id,
        bill_id=electricity.id,
        actor_user_id=seed.user_id,
        expected_version=electricity.version,
        amount_cents=30000,
        request_id=uuid4(),
    )
    db_session.commit()
    db_session.refresh(electricity)
    rows = bills.get_allocations(db_session, seed.household_id, electricity.id)
    assert [row.amount_cents for row in rows] == [6923, 11538, 11539]
    assert sum(row.amount_cents for row in rows) == 30000

    period = periods.get_period(db_session, seed.household_id, seed.period_id)
    assert period.version > 1


def test_void_bill_removes_allocations(db_session: Session, seed) -> None:
    trash = _bill_by_category(db_session, seed.period_id, "trash")
    bills.void_bill(
        db_session,
        household_id=seed.household_id,
        bill_id=trash.id,
        actor_user_id=seed.user_id,
        expected_version=trash.version,
        reason="重复录入",
        request_id=uuid4(),
    )
    db_session.commit()
    db_session.refresh(trash)
    assert trash.status == "voided"
    assert bills.get_allocations(db_session, seed.household_id, trash.id) == []


def test_stale_bill_version_conflicts(db_session: Session, seed) -> None:
    electricity = _bill_by_category(db_session, seed.period_id, "electricity")
    from roommate_billing.services.errors import ConflictError

    try:
        bills.update_bill(
            db_session,
            household_id=seed.household_id,
            bill_id=electricity.id,
            actor_user_id=seed.user_id,
            expected_version=electricity.version + 99,
            amount_cents=1,
            request_id=uuid4(),
        )
    except ConflictError as exc:
        assert exc.code == "VERSION_CONFLICT"
    else:
        raise AssertionError("expected ConflictError")


def test_locked_period_rejects_bill_write(db_session: Session, seed) -> None:
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
    from roommate_billing.services.errors import ConflictError

    try:
        bills.create_bill(
            db_session,
            household_id=seed.household_id,
            period_id=seed.period_id,
            actor_user_id=seed.user_id,
            category="other",
            name="锁定后新增",
            amount_cents=100,
            request_id=uuid4(),
        )
    except ConflictError as exc:
        assert exc.code == "PERIOD_NOT_OPEN"
    else:
        raise AssertionError("expected ConflictError")


def test_split_preview_does_not_write(db_session: Session, seed) -> None:
    before = db_session.scalar(select(func.count()).select_from(BillAllocation))
    preview = bills.split_preview(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        bills=[{"category": "electricity", "name": "假设电费", "amount_cents": 30000}],
    )
    after = db_session.scalar(select(func.count()).select_from(BillAllocation))
    assert before == after
    assert preview["grand_total_cents"] == 30000
    assert preview["bills"][0]["allocations"][0]["amount_cents"] == 6923
    assert preview["bills"][0]["allocations"][2]["amount_cents"] == 11539
    assert preview["bills"][0]["conservation_ok"] is True


def test_audit_entries_are_written(db_session: Session, seed) -> None:
    count = db_session.scalar(select(func.count()).select_from(AuditLog))
    assert count is not None and count >= 4
