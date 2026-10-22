"""结算预览、正式快照、解释与 CSV 导出。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import (
    Bill,
    BillAllocation,
    BillingPeriod,
    Payment,
    Person,
    Settlement,
    SettlementLine,
)
from ..domain.money import format_cents, format_cents_plain
from . import rules
from .audit import record_audit
from .errors import ConflictError, NotFoundError, ValidationError


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


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


def get_settlement(session: Session, household_id: UUID, settlement_id: UUID) -> Settlement:
    settlement = session.scalar(
        select(Settlement).where(
            Settlement.id == settlement_id,
            Settlement.household_id == household_id,
        )
    )
    if settlement is None:
        raise NotFoundError("结算不存在")
    return settlement


def lines_of(session: Session, settlement_id: UUID) -> list[SettlementLine]:
    return list(
        session.scalars(
            select(SettlementLine)
            .where(SettlementLine.settlement_id == settlement_id)
            .order_by(SettlementLine.display_order, SettlementLine.person_id)
        )
    )


def _people(session: Session, household_id: UUID, period_id: UUID) -> list[Person]:
    """结算参与人 = 活跃人员 ∪ 有分摊的人 ∪ 有付款的人。"""
    allocation_ids = (
        select(BillAllocation.person_id)
        .join(Bill, Bill.id == BillAllocation.bill_id)
        .where(Bill.period_id == period_id)
    )
    payment_ids = select(Payment.person_id).where(Payment.period_id == period_id)
    active_ids = select(Person.id).where(
        Person.household_id == household_id,
        Person.is_active.is_(True),
    )
    ids = set(session.scalars(active_ids))
    ids.update(session.scalars(allocation_ids))
    ids.update(session.scalars(payment_ids))
    if not ids:
        return []
    return list(
        session.scalars(
            select(Person)
            .where(Person.id.in_(ids), Person.household_id == household_id)
            .order_by(Person.slug, Person.id)
        )
    )


def _bill_snapshot(
    session: Session, household_id: UUID, period_id: UUID, people: list[Person]
) -> tuple[list[dict[str, Any]], dict[UUID, int], dict[UUID, int], int]:
    bills = list(
        session.scalars(
            select(Bill)
            .where(
                Bill.household_id == household_id,
                Bill.period_id == period_id,
                Bill.status == "active",
            )
            .order_by(Bill.created_at, Bill.id)
        )
    )
    allocated: dict[UUID, int] = {person.id: 0 for person in people}
    remainder: dict[UUID, int] = {person.id: 0 for person in people}
    snapshots: list[dict[str, Any]] = []
    bills_total = 0
    for bill in bills:
        rows = list(
            session.scalars(
                select(BillAllocation)
                .join(Person, Person.id == BillAllocation.person_id)
                .where(BillAllocation.bill_id == bill.id)
                .order_by(Person.slug, Person.id)
            )
        )
        if not rows:
            raise ConflictError("账单分摊不完整，请先重算")
        if sum(row.amount_cents for row in rows) != bill.amount_cents:
            raise ConflictError("账单分摊合计与账单金额不一致")
        bills_total += bill.amount_cents
        snapshots.append(
            {
                "bill_id": str(bill.id),
                "category": bill.category,
                "name": bill.name,
                "amount_cents": bill.amount_cents,
                "allocations": [
                    {
                        "person_id": str(row.person_id),
                        "weight_units": row.weight_units,
                        "base_cents": row.base_cents,
                        "remainder_cents": row.remainder_cents,
                        "amount_cents": row.amount_cents,
                        "is_remainder_owner": row.is_remainder_owner,
                    }
                    for row in rows
                ],
            }
        )
        for row in rows:
            allocated[row.person_id] = allocated.get(row.person_id, 0) + row.amount_cents
            remainder[row.person_id] = remainder.get(row.person_id, 0) + row.remainder_cents
    return snapshots, allocated, remainder, bills_total


def preview(session: Session, *, household_id: UUID, period_id: UUID) -> dict[str, Any]:
    period = get_period(session, household_id, period_id)
    rule, _items = rules.get_active_rule(session, household_id)
    rule_payload = rules.snapshot(session, rule)
    people = _people(session, household_id, period.id)
    bills_snapshot, allocated, remainder, bills_total = _bill_snapshot(
        session, household_id, period.id, people
    )
    if sum(allocated.values()) != bills_total:
        raise ConflictError("分摊合计与账单总额不一致")

    paid_rows = session.execute(
        select(Payment.person_id, func.coalesce(func.sum(Payment.amount_cents), 0))
        .where(
            Payment.household_id == household_id,
            Payment.period_id == period.id,
        )
        .group_by(Payment.person_id)
    )
    paid = {person.id: 0 for person in people}
    for person_id, total in paid_rows:
        paid[person_id] = int(total)
    payments_total = sum(paid.values())

    lines: list[dict[str, Any]] = []
    for index, person in enumerate(people):
        alloc = allocated.get(person.id, 0)
        pay = paid.get(person.id, 0)
        lines.append(
            {
                "person_id": str(person.id),
                "person_name": person.display_name,
                "person_slug": person.slug,
                "allocated_cents": alloc,
                "paid_cents": pay,
                "balance_cents": alloc - pay,
                "remainder_cents": remainder.get(person.id, 0),
                "display_order": index,
            }
        )
    balance_total = sum(line["balance_cents"] for line in lines)
    snapshot = {
        "period_id": str(period.id),
        "period_key": period.period_key,
        "period_version": period.version,
        "rule": rule_payload,
        "lines": lines,
        "bills_total_cents": bills_total,
        "payments_total_cents": payments_total,
        "balance_total_cents": balance_total,
    }
    return {
        "period_id": period.id,
        "period_key": period.period_key,
        "period_version": period.version,
        "rule_version_id": rule.id,
        "rule_snapshot": rule_payload,
        "bills_snapshot": {"bills": bills_snapshot},
        "lines": lines,
        "bills_total_cents": bills_total,
        "payments_total_cents": payments_total,
        "balance_total_cents": balance_total,
        "preview_hash": _hash(snapshot),
        "people": [
            {"person_id": str(person.id), "display_name": person.display_name} for person in people
        ],
    }


def create_settlement(
    session: Session,
    *,
    household_id: UUID,
    period_id: UUID,
    actor_user_id: UUID,
    expected_period_version: int,
    expected_preview_hash: str,
    note: str | None = None,
    request_id: UUID,
) -> tuple[Settlement, list[SettlementLine]]:
    period = get_period(session, household_id, period_id, for_update=True)
    if period.status != "locked":
        raise ConflictError("正式结算前必须锁定账期", code="PERIOD_NOT_LOCKED")
    if period.version != expected_period_version:
        raise ConflictError("账期已变化，请重新预览", code="VERSION_CONFLICT")
    data = preview(session, household_id=household_id, period_id=period_id)
    if data["preview_hash"] != expected_preview_hash:
        raise ConflictError("结算预览已过期，请重新预览", code="SETTLEMENT_PREVIEW_STALE")
    if len(data["lines"]) == 0:
        raise ValidationError("账期没有可结算人员")

    old_final = session.scalar(
        select(Settlement)
        .where(
            Settlement.period_id == period.id,
            Settlement.status == "final",
        )
        .with_for_update()
    )
    if old_final is not None:
        old_final.status = "superseded"
        old_final.superseded_at = utcnow()
        session.flush()

    revision = (
        session.scalar(
            select(func.max(Settlement.revision)).where(Settlement.period_id == period.id)
        )
        or 0
    ) + 1
    settlement = Settlement(
        household_id=household_id,
        period_id=period.id,
        revision=revision,
        status="final",
        rule_version_id=data["rule_version_id"],
        rule_snapshot=data["rule_snapshot"],
        bills_snapshot=data["bills_snapshot"],
        bills_total_cents=data["bills_total_cents"],
        payments_total_cents=data["payments_total_cents"],
        balance_total_cents=data["balance_total_cents"],
        created_by=actor_user_id,
        supersedes_id=old_final.id if old_final else None,
        note=note,
        request_id=request_id,
    )
    session.add(settlement)
    session.flush()

    settlement_lines: list[SettlementLine] = []
    for line in data["lines"]:
        row = SettlementLine(
            household_id=household_id,
            settlement_id=settlement.id,
            person_id=UUID(line["person_id"]),
            allocated_cents=line["allocated_cents"],
            paid_cents=line["paid_cents"],
            balance_cents=line["balance_cents"],
            remainder_cents=line["remainder_cents"],
            display_order=line["display_order"],
        )
        session.add(row)
        settlement_lines.append(row)
    period.status = "settled"
    period.settled_at = utcnow()
    period.version += 1
    period.updated_at = utcnow()
    session.flush()

    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="settlement.create",
        entity_type="settlement",
        entity_id=settlement.id,
        after={
            "revision": revision,
            "period_key": period.period_key,
            "bills_total_cents": settlement.bills_total_cents,
            "payments_total_cents": settlement.payments_total_cents,
            "balance_total_cents": settlement.balance_total_cents,
        },
        request_id=request_id,
    )
    return settlement, settlement_lines


def list_settlements(session: Session, household_id: UUID, period_id: UUID) -> list[Settlement]:
    return list(
        session.scalars(
            select(Settlement)
            .where(
                Settlement.household_id == household_id,
                Settlement.period_id == period_id,
            )
            .order_by(Settlement.revision.desc())
        )
    )


def explain(
    session: Session, *, household_id: UUID, settlement_id: UUID, person_id: UUID
) -> dict[str, Any]:
    settlement = get_settlement(session, household_id, settlement_id)
    line = session.scalar(
        select(SettlementLine).where(
            SettlementLine.settlement_id == settlement.id,
            SettlementLine.person_id == person_id,
        )
    )
    if line is None:
        raise NotFoundError("该人员不在结算中")
    person = session.get(Person, person_id)
    components: list[dict[str, Any]] = []
    for bill in settlement.bills_snapshot.get("bills", []):
        for allocation in bill.get("allocations", []):
            if allocation.get("person_id") == str(person_id):
                components.append(
                    {
                        "bill_id": bill["bill_id"],
                        "bill_name": bill["name"],
                        "category": bill["category"],
                        "amount_cents": bill["amount_cents"],
                        "weight_units": allocation["weight_units"],
                        "base_cents": allocation["base_cents"],
                        "remainder_cents": allocation["remainder_cents"],
                        "allocated_cents": allocation["amount_cents"],
                    }
                )
    display = (
        f"应承担 {format_cents(line.allocated_cents)} − "
        f"已收 {format_cents(line.paid_cents)} = "
        f"{format_cents(line.balance_cents)}"
    )
    return {
        "settlement_id": str(settlement.id),
        "revision": settlement.revision,
        "person_id": str(person_id),
        "person_name": person.display_name if person else None,
        "allocated_cents": line.allocated_cents,
        "paid_cents": line.paid_cents,
        "balance_cents": line.balance_cents,
        "remainder_cents": line.remainder_cents,
        "components": components,
        "rule_snapshot": settlement.rule_snapshot,
        "explanation": display,
    }


def export_csv(session: Session, *, household_id: UUID, settlement_id: UUID) -> tuple[str, str]:
    settlement = get_settlement(session, household_id, settlement_id)
    period = get_period(session, household_id, settlement.period_id)
    lines = lines_of(session, settlement.id)
    people = {person.id: person for person in _people(session, household_id, settlement.period_id)}
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        [
            "period",
            "revision",
            "person",
            "allocated_yuan",
            "paid_yuan",
            "balance_yuan",
            "remainder_cents",
        ]
    )
    for line in lines:
        person = people.get(line.person_id)
        writer.writerow(
            [
                period.period_key,
                settlement.revision,
                person.display_name if person else str(line.person_id),
                format_cents_plain(line.allocated_cents),
                format_cents_plain(line.paid_cents),
                format_cents_plain(line.balance_cents),
                line.remainder_cents,
            ]
        )
    # 防 CSV 公式注入：以 = + - @ 开头的文本加单引号。
    text = output.getvalue()
    safe_lines = []
    for row in csv.reader(io.StringIO(text)):
        safe_lines.append(["'" + cell if cell and cell[0] in "=+-@\t\r" else cell for cell in row])
    safe_output = io.StringIO()
    csv.writer(safe_output, lineterminator="\n").writerows(safe_lines)
    filename = f"settlement-{settlement.period_id}-r{settlement.revision}.csv"
    return filename, safe_output.getvalue()
