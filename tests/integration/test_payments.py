"""实际收款服务测试。"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from roommate_billing.db.models import Payment
from roommate_billing.services import payments
from roommate_billing.services.errors import ConflictError, ValidationError


def test_record_payments_and_totals(db_session: Session, seed) -> None:
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
    totals = payments.totals_by_person(db_session, seed.household_id, seed.period_id)
    assert totals[seed.people["lin"]] == 11378
    assert sum(totals.values()) == 49305
    assert len(payments.list_payments(db_session, seed.household_id, seed.period_id)) == 3


def test_adjustment_preserves_original(db_session: Session, seed) -> None:
    original = payments.record_payment(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        person_id=seed.people["lin"],
        amount_cents=10000,
        paid_on=date(2026, 10, 5),
        method="bank",
        request_id=uuid4(),
    )
    db_session.commit()
    adjustment = payments.adjust_payment(
        db_session,
        household_id=seed.household_id,
        original_payment_id=original.id,
        actor_user_id=seed.user_id,
        amount_cents=-1000,
        reason="金额录错",
        request_id=uuid4(),
    )
    db_session.commit()
    db_session.refresh(original)
    assert original.amount_cents == 10000
    assert adjustment.amount_cents == -1000
    assert adjustment.adjusts_payment_id == original.id
    totals = payments.totals_by_person(db_session, seed.household_id, seed.period_id)
    assert totals[seed.people["lin"]] == 9000


def test_adjustment_cannot_over_adjust(db_session: Session, seed) -> None:
    original = payments.record_payment(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        person_id=seed.people["lin"],
        amount_cents=1000,
        paid_on=date(2026, 10, 5),
        method="bank",
        request_id=uuid4(),
    )
    db_session.commit()
    with pytest.raises(ValidationError):
        payments.adjust_payment(
            db_session,
            household_id=seed.household_id,
            original_payment_id=original.id,
            actor_user_id=seed.user_id,
            amount_cents=-1001,
            reason="超额",
            request_id=uuid4(),
        )


def test_payment_append_only_trigger(db_session: Session, seed) -> None:
    payment = payments.record_payment(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        person_id=seed.people["lin"],
        amount_cents=1000,
        paid_on=date(2026, 10, 5),
        method="bank",
        request_id=uuid4(),
    )
    db_session.commit()
    with pytest.raises(DBAPIError):
        db_session.execute(
            update(Payment).where(Payment.id == payment.id).values(amount_cents=2000)
        )
        db_session.commit()
    db_session.rollback()


def test_settled_period_blocks_payment(db_session: Session, seed) -> None:
    from roommate_billing.services import periods, settlements

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
    settlements.create_settlement(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        expected_period_version=preview["period_version"],
        expected_preview_hash=preview["preview_hash"],
        request_id=uuid4(),
    )
    db_session.commit()
    with pytest.raises(ConflictError):
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
