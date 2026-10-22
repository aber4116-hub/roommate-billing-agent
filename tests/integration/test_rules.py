"""规则版本服务测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from roommate_billing.db.models import Bill, BillAllocation, RuleVersion
from roommate_billing.services import bills, periods, rules
from roommate_billing.services.errors import ConflictError, ValidationError


def _items(water_method: str = "equal_household") -> list[dict[str, str]]:
    return [
        {"category": "electricity", "split_method": "days", "fallback_method": "equal_household"},
        {"category": "water", "split_method": water_method, "fallback_method": "equal_household"},
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


def _water_allocations(db_session: Session, period_id) -> list[int]:
    water = db_session.scalar(
        select(Bill).where(Bill.period_id == period_id, Bill.category == "water")
    )
    rows = list(
        db_session.scalars(
            select(BillAllocation)
            .where(BillAllocation.bill_id == water.id)
            .order_by(BillAllocation.created_at)
        )
    )
    return [row.amount_cents for row in rows]


def test_preview_and_activate_rule(db_session: Session, seed) -> None:
    draft = rules.create_draft(
        db_session,
        household_id=seed.household_id,
        owner_person_id=seed.people["zhou"],
        items=_items("equal_household"),
        note="水费改为按户",
        actor_user_id=seed.user_id,
        request_id=uuid4(),
    )
    db_session.commit()
    assert draft.status == "draft"
    assert _water_allocations(db_session, seed.period_id) == [2224, 3707, 3709]

    draft, preview = rules.preview_rule(
        db_session,
        household_id=seed.household_id,
        rule_version_id=draft.id,
        actor_user_id=seed.user_id,
        request_id=uuid4(),
    )
    db_session.commit()
    assert preview["periods"][0]["after"][str(seed.people["lin"])] == 12494 + 989
    assert draft.preview_hash

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

    assert _water_allocations(db_session, seed.period_id) == [3213, 3213, 3214]
    active = db_session.scalar(
        select(RuleVersion).where(
            RuleVersion.household_id == seed.household_id,
            RuleVersion.status == "active",
        )
    )
    assert active.id == draft.id
    old = db_session.scalar(
        select(RuleVersion).where(
            RuleVersion.household_id == seed.household_id,
            RuleVersion.version_no == 1,
        )
    )
    assert old.status == "archived"


def test_activation_rejects_stale_preview(db_session: Session, seed) -> None:
    draft = rules.create_draft(
        db_session,
        household_id=seed.household_id,
        owner_person_id=seed.people["zhou"],
        items=_items(),
        note="预览后修改",
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
    old_hash = draft.preview_hash
    assert old_hash

    electricity = db_session.scalar(
        select(Bill).where(Bill.period_id == seed.period_id, Bill.category == "electricity")
    )
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

    with pytest.raises(ConflictError) as exc_info:
        rules.activate_rule(
            db_session,
            household_id=seed.household_id,
            rule_version_id=draft.id,
            expected_active_version_no=1,
            expected_preview_hash=old_hash,
            expected_row_version=1,
            actor_user_id=seed.user_id,
            request_id=uuid4(),
        )
    assert exc_info.value.code == "RULE_PREVIEW_STALE"


def test_rule_requires_all_categories(db_session: Session, seed) -> None:
    with pytest.raises(ValidationError):
        rules.create_draft(
            db_session,
            household_id=seed.household_id,
            owner_person_id=seed.people["zhou"],
            items=_items()[:-1],
            note="缺 other",
            actor_user_id=seed.user_id,
            request_id=uuid4(),
        )


def test_period_lock_still_works_after_rule_activation(db_session: Session, seed) -> None:
    # 仅验证规则激活后可正常锁定，不产生结算。
    draft = rules.create_draft(
        db_session,
        household_id=seed.household_id,
        owner_person_id=seed.people["zhou"],
        items=_items(),
        note="noop",
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
    fresh = periods.get_period(db_session, seed.household_id, seed.period_id)
    periods.lock_period(
        db_session,
        household_id=seed.household_id,
        period_id=seed.period_id,
        actor_user_id=seed.user_id,
        expected_version=fresh.version,
        request_id=uuid4(),
    )
    db_session.commit()
    assert periods.get_period(db_session, seed.household_id, seed.period_id).status == "locked"
