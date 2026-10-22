"""账单服务：创建、修改、作废、重算与预览。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import Bill, BillAllocation, BillingPeriod, Person
from ..domain.money import MAX_BILL_CENTS, validate_cents
from . import allocations, rules
from .audit import record_audit
from .errors import ConflictError, NotFoundError, ValidationError

CATEGORIES = rules.CATEGORIES


def get_period(
    session: Session, household_id: UUID, period_id: UUID, *, for_update: bool = False
) -> BillingPeriod:
    statement = select(BillingPeriod).where(
        BillingPeriod.id == period_id,
        BillingPeriod.household_id == household_id,
    )
    if for_update:
        statement = statement.with_for_update()
    period = session.scalar(statement)
    if period is None:
        raise NotFoundError("账期不存在")
    return period


def get_bill(
    session: Session, household_id: UUID, bill_id: UUID, *, for_update: bool = False
) -> Bill:
    statement = select(Bill).where(
        Bill.id == bill_id,
        Bill.household_id == household_id,
    )
    if for_update:
        statement = statement.with_for_update()
    bill = session.scalar(statement)
    if bill is None:
        raise NotFoundError("账单不存在")
    return bill


def _validate_bill_input(category: str, name: str, amount_cents: int) -> None:
    if category not in CATEGORIES:
        raise ValidationError(f"未知账单分类：{category}")
    if not name or len(name) > 120:
        raise ValidationError("账单名称长度必须为 1–120")
    validate_cents(amount_cents, max_abs_cents=MAX_BILL_CENTS)


def _bump_period(period: BillingPeriod) -> None:
    period.version += 1
    period.updated_at = utcnow()


def bill_snapshot(
    session: Session, bill: Bill, results: list[BillAllocation] | None = None
) -> dict[str, Any]:
    if results is None:
        results = list(
            session.scalars(
                select(BillAllocation)
                .join(Person, Person.id == BillAllocation.person_id)
                .where(BillAllocation.bill_id == bill.id)
                .order_by(Person.slug, Person.id)
            )
        )
    return {
        "bill_id": str(bill.id),
        "category": bill.category,
        "name": bill.name,
        "amount_cents": bill.amount_cents,
        "status": bill.status,
        "version": bill.version,
        "allocations": [
            {
                "person_id": str(row.person_id),
                "weight_units": row.weight_units,
                "base_cents": row.base_cents,
                "remainder_cents": row.remainder_cents,
                "amount_cents": row.amount_cents,
                "is_remainder_owner": row.is_remainder_owner,
            }
            for row in results
        ],
    }


def create_bill(
    session: Session,
    *,
    household_id: UUID,
    period_id: UUID,
    actor_user_id: UUID,
    category: str,
    name: str,
    amount_cents: int,
    incurred_on: date | None = None,
    request_id: UUID | None = None,
) -> Bill:
    _validate_bill_input(category, name, amount_cents)
    period = get_period(session, household_id, period_id, for_update=True)
    if period.status != "open":
        raise ConflictError("只有开放账期可以新增账单", code="PERIOD_NOT_OPEN")

    rule, items = rules.get_active_rule(session, household_id)
    payload = rules.to_payload(rule, items)
    people = allocations.load_active_people(session, household_id)
    if not people:
        raise ConflictError("账本没有有效人员")

    bill = Bill(
        household_id=household_id,
        period_id=period.id,
        category=category,
        name=name.strip(),
        amount_cents=amount_cents,
        incurred_on=incurred_on,
        status="active",
        version=1,
        created_by=actor_user_id,
    )
    session.add(bill)
    session.flush()

    occupancy = allocations.load_occupancy_map(session, period.id)
    allocations.replace_bill_allocations(session, bill, people, occupancy, payload)
    _bump_period(period)
    session.flush()

    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="bill.create",
        entity_type="bill",
        entity_id=bill.id,
        after=bill_snapshot(session, bill),
        request_id=request_id,
    )
    return bill


def update_bill(
    session: Session,
    *,
    household_id: UUID,
    bill_id: UUID,
    actor_user_id: UUID,
    expected_version: int,
    name: str | None = None,
    amount_cents: int | None = None,
    incurred_on: date | None = None,
    request_id: UUID | None = None,
) -> Bill:
    bill = get_bill(session, household_id, bill_id, for_update=True)
    period = get_period(session, household_id, bill.period_id, for_update=True)
    if period.status != "open":
        raise ConflictError("只有开放账期可以修改账单", code="PERIOD_NOT_OPEN")
    if bill.version != expected_version:
        raise ConflictError("账单已被其他人修改，请刷新后重试", code="VERSION_CONFLICT")
    before = bill_snapshot(session, bill)

    if name is not None:
        if not name or len(name) > 120:
            raise ValidationError("账单名称长度必须为 1–120")
        bill.name = name.strip()
    if amount_cents is not None:
        _validate_bill_input(bill.category, bill.name, amount_cents)
        bill.amount_cents = amount_cents
    if incurred_on is not None:
        bill.incurred_on = incurred_on
    bill.version += 1
    bill.updated_at = utcnow()

    rule, items = rules.get_active_rule(session, household_id)
    payload = rules.to_payload(rule, items)
    people = allocations.load_active_people(session, household_id)
    occupancy = allocations.load_occupancy_map(session, period.id)
    allocations.replace_bill_allocations(session, bill, people, occupancy, payload)
    _bump_period(period)
    session.flush()

    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="bill.update",
        entity_type="bill",
        entity_id=bill.id,
        before=before,
        after=bill_snapshot(session, bill),
        request_id=request_id,
    )
    return bill


def void_bill(
    session: Session,
    *,
    household_id: UUID,
    bill_id: UUID,
    actor_user_id: UUID,
    expected_version: int,
    reason: str,
    request_id: UUID | None = None,
) -> Bill:
    bill = get_bill(session, household_id, bill_id, for_update=True)
    period = get_period(session, household_id, bill.period_id, for_update=True)
    if period.status != "open":
        raise ConflictError("只有开放账期可以作废账单", code="PERIOD_NOT_OPEN")
    if bill.version != expected_version:
        raise ConflictError("账单已被其他人修改，请刷新后重试", code="VERSION_CONFLICT")
    if not reason or len(reason) > 300:
        raise ValidationError("作废原因长度必须为 1–300")
    before = bill_snapshot(session, bill)

    bill.status = "voided"
    bill.voided_at = utcnow()
    bill.voided_by = actor_user_id
    bill.void_reason = reason
    bill.version += 1
    bill.updated_at = utcnow()
    session.execute(BillAllocation.__table__.delete().where(BillAllocation.bill_id == bill.id))
    _bump_period(period)
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="bill.void",
        entity_type="bill",
        entity_id=bill.id,
        before=before,
        after={"status": "voided", "reason": reason},
        request_id=request_id,
    )
    return bill


def list_bills(
    session: Session, household_id: UUID, period_id: UUID, *, include_voided: bool = False
) -> list[Bill]:
    statement = select(Bill).where(
        Bill.household_id == household_id,
        Bill.period_id == period_id,
    )
    if not include_voided:
        statement = statement.where(Bill.status == "active")
    return list(session.scalars(statement.order_by(Bill.created_at, Bill.id)))


def get_allocations(session: Session, household_id: UUID, bill_id: UUID) -> list[BillAllocation]:
    get_bill(session, household_id, bill_id)
    return list(
        session.scalars(
            select(BillAllocation)
            .join(Person, Person.id == BillAllocation.person_id)
            .where(BillAllocation.bill_id == bill_id)
            .order_by(Person.slug, Person.id)
        )
    )


def split_preview(
    session: Session,
    *,
    household_id: UUID,
    period_id: UUID,
    rule_version_id: UUID | None = None,
    occupancies: list[dict[str, Any]] | None = None,
    bills: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """只读预览：不写账单/分摊。"""
    period = get_period(session, household_id, period_id)
    if rule_version_id:
        rule, items = rules.get_rule(session, household_id, rule_version_id)
    else:
        rule, items = rules.get_active_rule(session, household_id)
    payload = rules.to_payload(rule, items)
    people = allocations.load_active_people(session, household_id)
    if not people:
        raise ConflictError("账本没有有效人员")

    if occupancies is None:
        occupancy = allocations.load_occupancy_map(session, period.id)
    else:
        occupancy = {item["person_id"]: item["days"] for item in occupancies}
        for person_id, days in occupancy.items():
            if person_id not in {person.id for person in people}:
                raise ValidationError("入住天数包含非本账本人员")
            if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 31:
                raise ValidationError("入住天数必须是 0–31 的整数")

    if bills is None:
        bill_rows = list(
            session.scalars(
                select(Bill).where(
                    Bill.period_id == period.id,
                    Bill.status == "active",
                )
            )
        )
        inputs = [
            SimpleNamespace(
                id=bill.id,
                category=bill.category,
                name=bill.name,
                amount_cents=bill.amount_cents,
            )
            for bill in bill_rows
        ]
    else:
        inputs = []
        for index, item in enumerate(bills):
            category = item["category"]
            name = item.get("name") or category
            amount = item["amount_cents"]
            _validate_bill_input(category, name, amount)
            inputs.append(
                SimpleNamespace(
                    id=f"preview-{index}",
                    category=category,
                    name=name,
                    amount_cents=amount,
                )
            )

    result: dict[str, Any] = {
        "rule_version_id": str(rule.id),
        "remainder_owner_person_id": str(rule.remainder_owner_person_id),
        "people": [
            {"person_id": str(person.id), "display_name": person.display_name} for person in people
        ],
        "bills": [],
        "person_totals": {str(person.id): 0 for person in people},
        "grand_total_cents": 0,
    }
    for bill in inputs:
        allocation = allocations.compute_bill_allocation(bill, people, occupancy, payload)
        result["bills"].append(
            {
                "bill_key": str(bill.id),
                "category": bill.category,
                "name": bill.name,
                "amount_cents": bill.amount_cents,
                "shares_total_cents": sum(allocation.amounts),
                "conservation_ok": sum(allocation.amounts) == bill.amount_cents,
                "allocations": [
                    {
                        "person_id": str(person.id),
                        "amount_cents": line.amount_cents,
                        "base_cents": line.base_cents,
                        "remainder_cents": line.remainder_cents,
                        "is_remainder_owner": line.is_remainder_owner,
                    }
                    for person, line in zip(people, allocation.lines, strict=True)
                ],
            }
        )
        for index, person in enumerate(people):
            result["person_totals"][str(person.id)] += allocation.amounts[index]
        result["grand_total_cents"] += bill.amount_cents
    return result
