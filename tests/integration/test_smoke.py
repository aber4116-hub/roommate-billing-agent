"""阶段 3 冒烟：种子账本、账单分摊、预览与结算。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from roommate_billing.db.models import Bill, BillAllocation
from roommate_billing.services import periods, settlements


def test_seed_and_settlement_smoke(db_session: Session, seed) -> None:
    bill_rows = list(db_session.scalars(select(Bill).where(Bill.period_id == seed.period_id)))
    assert len(bill_rows) == 4
    allocations = list(
        db_session.scalars(
            select(BillAllocation).where(
                BillAllocation.bill_id.in_([bill.id for bill in bill_rows])
            )
        )
    )
    assert len(allocations) == 12
    assert sum(row.amount_cents for row in allocations) == 49305

    preview = settlements.preview(
        db_session, household_id=seed.household_id, period_id=seed.period_id
    )
    assert preview["bills_total_cents"] == 49305
    assert preview["lines"][0]["person_id"] == str(seed.people["lin"])

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
    assert settlement.revision == 1
    assert len(lines) == 3
    assert sum(line.allocated_cents for line in lines) == 49305
    assert db_session.scalar(select(func.count()).select_from(Bill)) == 4
