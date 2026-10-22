"""把纯分摊引擎接到数据库：加载人员/天数/规则，并持久化分摊行。"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db.models import Bill, BillAllocation, BillingPeriod, Occupancy, Person
from ..domain.allocation import AllocationResult, split_cents
from .errors import ConflictError
from .rule_types import RulePayload


def load_active_people(session: Session, household_id: UUID) -> list[Person]:
    """按稳定顺序返回活跃人员；历史归属不依赖数组下标。"""
    statement = (
        select(Person)
        .where(Person.household_id == household_id, Person.is_active.is_(True))
        .order_by(Person.slug, Person.id)
    )
    return list(session.scalars(statement))


def load_occupancy_map(session: Session, period_id: UUID) -> dict[UUID, int]:
    rows = session.scalars(select(Occupancy).where(Occupancy.period_id == period_id))
    return {row.person_id: row.days for row in rows}


def compute_bill_allocation(
    bill: Bill,
    people: Sequence[Person],
    occupancy: dict[UUID, int],
    rule: RulePayload,
) -> AllocationResult:
    if not people:
        raise ConflictError("账本没有可用人员，无法分摊")
    if rule.owner_person_id not in {person.id for person in people}:
        raise ConflictError("规则指定的零头归属人不是当前有效人员")

    method = rule.methods.get(bill.category)
    if method is None:
        raise ConflictError(f"当前规则缺少账单分类 {bill.category}")

    if method == "days":
        weights = [occupancy.get(person.id, 0) for person in people]
    elif method == "equal_household":
        weights = [1 for _ in people]
    else:
        raise ConflictError(f"未知分摊方法 {method}")

    owner_index = next(
        index for index, person in enumerate(people) if person.id == rule.owner_person_id
    )
    return split_cents(
        bill.amount_cents,
        weights,
        owner_index=owner_index,
    )


def compute_period_allocations(
    session: Session,
    period: BillingPeriod,
    rule: RulePayload,
    *,
    people: Sequence[Person] | None = None,
) -> dict[UUID, AllocationResult]:
    """计算一个账期所有有效账单的分摊，不写数据库。"""
    people = (
        list(people) if people is not None else load_active_people(session, period.household_id)
    )
    occupancy = load_occupancy_map(session, period.id)
    bills = list(
        session.scalars(
            select(Bill).where(
                Bill.period_id == period.id,
                Bill.status == "active",
            )
        )
    )
    return {bill.id: compute_bill_allocation(bill, people, occupancy, rule) for bill in bills}


def replace_bill_allocations(
    session: Session,
    bill: Bill,
    people: Sequence[Person],
    occupancy: dict[UUID, int],
    rule: RulePayload,
) -> AllocationResult:
    """删除旧分摊并写入新分摊；调用方负责事务提交。"""
    session.execute(delete(BillAllocation).where(BillAllocation.bill_id == bill.id))
    result = compute_bill_allocation(bill, people, occupancy, rule)

    for person, line in zip(people, result.lines, strict=True):
        session.add(
            BillAllocation(
                household_id=bill.household_id,
                bill_id=bill.id,
                person_id=person.id,
                rule_version_id=rule.rule_version_id,
                weight_units=line.weight,
                base_cents=line.base_cents,
                remainder_cents=line.remainder_cents,
                amount_cents=line.amount_cents,
                is_remainder_owner=line.is_remainder_owner,
            )
        )
    return result


def reallocate_period(
    session: Session,
    period: BillingPeriod,
    rule: RulePayload,
    *,
    people: Sequence[Person] | None = None,
) -> dict[UUID, AllocationResult]:
    """重算一个账期的所有开放账单；调用方保证账期状态与锁。"""
    people = (
        list(people) if people is not None else load_active_people(session, period.household_id)
    )
    occupancy = load_occupancy_map(session, period.id)
    bills = list(
        session.scalars(
            select(Bill).where(
                Bill.period_id == period.id,
                Bill.status == "active",
            )
        )
    )
    results: dict[UUID, AllocationResult] = {}
    for bill in bills:
        results[bill.id] = replace_bill_allocations(session, bill, people, occupancy, rule)
    return results
