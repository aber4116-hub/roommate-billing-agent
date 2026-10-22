"""规则版本：创建、预览影响、激活并重算开放账期。"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import (
    Bill,
    BillAllocation,
    BillingPeriod,
    Person,
    RuleVersion,
    RuleVersionItem,
)
from . import allocations
from .audit import record_audit
from .errors import ConflictError, NotFoundError, ValidationError
from .rule_types import RulePayload

CATEGORIES = ("electricity", "water", "internet", "trash", "other")
SPLIT_METHODS = ("days", "equal_household")
FALLBACK_METHODS = ("equal_household",)


def _hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_items(items: list[dict[str, str]]) -> dict[str, str]:
    methods: dict[str, str] = {}
    for item in items:
        category = item.get("category", "")
        method = item.get("split_method", "")
        fallback = item.get("fallback_method", "equal_household")
        if category not in CATEGORIES:
            raise ValidationError(f"未知账单分类：{category}")
        if category in methods:
            raise ValidationError(f"分类重复：{category}")
        if method not in SPLIT_METHODS:
            raise ValidationError(f"未知分摊方法：{method}")
        if fallback not in FALLBACK_METHODS:
            raise ValidationError(f"未知备用规则：{fallback}")
        methods[category] = method
    missing = set(CATEGORIES) - set(methods)
    if missing:
        raise ValidationError(f"规则缺少分类：{', '.join(sorted(missing))}")
    return methods


def config_hash(owner_person_id: UUID, methods: dict[str, str]) -> str:
    return _hash(
        {
            "owner_person_id": str(owner_person_id),
            "items": [
                {"category": category, "split_method": methods[category]}
                for category in sorted(methods)
            ],
        }
    )


def load_items(session: Session, rule_version_id: UUID) -> list[RuleVersionItem]:
    return list(
        session.scalars(
            select(RuleVersionItem)
            .where(RuleVersionItem.rule_version_id == rule_version_id)
            .order_by(RuleVersionItem.category)
        )
    )


def to_payload(rule: RuleVersion, items: list[RuleVersionItem]) -> RulePayload:
    return RulePayload(
        rule_version_id=rule.id,
        owner_person_id=rule.remainder_owner_person_id,
        methods={item.category: item.split_method for item in items},
    )


def get_rule(
    session: Session, household_id: UUID, rule_version_id: UUID
) -> tuple[RuleVersion, list[RuleVersionItem]]:
    rule = session.scalar(
        select(RuleVersion).where(
            RuleVersion.id == rule_version_id,
            RuleVersion.household_id == household_id,
        )
    )
    if rule is None:
        raise NotFoundError("规则版本不存在")
    return rule, load_items(session, rule.id)


def get_active_rule(
    session: Session, household_id: UUID, *, for_update: bool = False
) -> tuple[RuleVersion, list[RuleVersionItem]]:
    statement = select(RuleVersion).where(
        RuleVersion.household_id == household_id,
        RuleVersion.status == "active",
    )
    if for_update:
        statement = statement.with_for_update()
    rule = session.scalar(statement)
    if rule is None:
        raise ConflictError("账本没有生效中的规则版本")
    return rule, load_items(session, rule.id)


def active_payload(session: Session, household_id: UUID) -> RulePayload:
    rule, items = get_active_rule(session, household_id)
    return to_payload(rule, items)


def validate_owner(session: Session, household_id: UUID, owner_person_id: UUID) -> Person:
    person = session.scalar(
        select(Person).where(
            Person.id == owner_person_id,
            Person.household_id == household_id,
            Person.is_active.is_(True),
        )
    )
    if person is None:
        raise ValidationError("零头归属人必须是本账本的有效人员")
    return person


def create_initial_rule(
    session: Session,
    *,
    household_id: UUID,
    owner_person_id: UUID,
    actor_user_id: UUID,
    request_id: UUID | None = None,
) -> RuleVersion:
    validate_owner(session, household_id, owner_person_id)
    existing = session.scalar(
        select(func.count())
        .select_from(RuleVersion)
        .where(RuleVersion.household_id == household_id)
    )
    if existing:
        raise ConflictError("账本已存在规则版本")
    methods = {
        "electricity": "days",
        "water": "days",
        "internet": "equal_household",
        "trash": "equal_household",
        "other": "equal_household",
    }
    rule = RuleVersion(
        household_id=household_id,
        version_no=1,
        status="active",
        row_version=1,
        remainder_owner_person_id=owner_person_id,
        config_hash=config_hash(owner_person_id, methods),
        note="初始化规则",
        created_by=actor_user_id,
        activated_by=actor_user_id,
        activated_at=utcnow(),
    )
    session.add(rule)
    session.flush()
    for category in CATEGORIES:
        session.add(
            RuleVersionItem(
                household_id=household_id,
                rule_version_id=rule.id,
                category=category,
                split_method=methods[category],
                fallback_method="equal_household",
                config={},
            )
        )
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="rule.initial_create",
        entity_type="rule_version",
        entity_id=rule.id,
        after={"version_no": 1, "methods": methods, "owner_person_id": str(owner_person_id)},
        request_id=request_id,
    )
    return rule


def create_draft(
    session: Session,
    *,
    household_id: UUID,
    owner_person_id: UUID,
    items: list[dict[str, str]],
    note: str,
    actor_user_id: UUID,
    request_id: UUID | None = None,
) -> RuleVersion:
    validate_owner(session, household_id, owner_person_id)
    methods = _validate_items(items)
    next_no = (
        session.scalar(
            select(func.max(RuleVersion.version_no)).where(RuleVersion.household_id == household_id)
        )
        or 0
    ) + 1
    rule = RuleVersion(
        household_id=household_id,
        version_no=next_no,
        status="draft",
        row_version=1,
        remainder_owner_person_id=owner_person_id,
        config_hash=config_hash(owner_person_id, methods),
        note=note,
        created_by=actor_user_id,
    )
    session.add(rule)
    session.flush()
    for category in CATEGORIES:
        session.add(
            RuleVersionItem(
                household_id=household_id,
                rule_version_id=rule.id,
                category=category,
                split_method=methods[category],
                fallback_method="equal_household",
                config={},
            )
        )
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="rule.draft_create",
        entity_type="rule_version",
        entity_id=rule.id,
        after={"version_no": next_no, "methods": methods, "owner_person_id": str(owner_person_id)},
        request_id=request_id,
    )
    return rule


def _current_allocations(
    session: Session, period_id: UUID, people: list[Person]
) -> dict[UUID, dict[UUID, int]]:
    bills = list(
        session.scalars(select(Bill).where(Bill.period_id == period_id, Bill.status == "active"))
    )
    by_bill: dict[UUID, dict[UUID, int]] = {bill.id: {} for bill in bills}
    rows = session.scalars(
        select(BillAllocation).where(BillAllocation.bill_id.in_([bill.id for bill in bills]))
    )
    for row in rows:
        by_bill.setdefault(row.bill_id, {})[row.person_id] = row.amount_cents
    for bill in bills:
        if set(by_bill.get(bill.id, {})) != {person.id for person in people}:
            raise ConflictError("账期分摊不完整，请先重算")
    return by_bill


def _period_person_totals(
    allocations_by_bill: dict[UUID, dict[UUID, int]], people: list[Person]
) -> dict[UUID, int]:
    totals = {person.id: 0 for person in people}
    for by_person in allocations_by_bill.values():
        for person_id, amount in by_person.items():
            totals[person_id] = totals.get(person_id, 0) + amount
    return totals


def preview_rule(
    session: Session,
    *,
    household_id: UUID,
    rule_version_id: UUID,
    actor_user_id: UUID,
    request_id: UUID | None = None,
) -> tuple[RuleVersion, dict[str, Any]]:
    rule, items = get_rule(session, household_id, rule_version_id)
    if rule.status != "draft":
        raise ConflictError("只有草稿规则可以预览")
    payload = to_payload(rule, items)
    people = allocations.load_active_people(session, household_id)
    periods = list(
        session.scalars(
            select(BillingPeriod)
            .where(
                BillingPeriod.household_id == household_id,
                BillingPeriod.status == "open",
            )
            .order_by(BillingPeriod.period_key)
        )
    )
    snapshot_periods: list[dict[str, Any]] = []
    for period in periods:
        before_by_bill = _current_allocations(session, period.id, people)
        after = allocations.compute_period_allocations(session, period, payload, people=people)
        before_totals = _period_person_totals(before_by_bill, people)
        after_totals = {person.id: 0 for person in people}
        for result in after.values():
            for index, person in enumerate(people):
                after_totals[person.id] += result.amounts[index]
        snapshot_periods.append(
            {
                "period_id": str(period.id),
                "period_key": period.period_key,
                "period_version": period.version,
                "before": {str(key): value for key, value in before_totals.items()},
                "after": {str(key): value for key, value in after_totals.items()},
                "delta": {
                    str(person.id): after_totals[person.id] - before_totals[person.id]
                    for person in people
                },
            }
        )
    snapshot = {
        "rule_version_id": str(rule.id),
        "version_no": rule.version_no,
        "owner_person_id": str(rule.remainder_owner_person_id),
        "config_hash": rule.config_hash,
        "periods": snapshot_periods,
    }
    digest = _hash(snapshot)
    rule.preview_snapshot = snapshot
    rule.preview_hash = digest
    rule.previewed_at = utcnow()
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="rule.preview",
        entity_type="rule_version",
        entity_id=rule.id,
        after={"preview_hash": digest, "periods": snapshot_periods},
        request_id=request_id,
    )
    return rule, snapshot


def activate_rule(
    session: Session,
    *,
    household_id: UUID,
    rule_version_id: UUID,
    expected_active_version_no: int,
    expected_preview_hash: str,
    expected_row_version: int,
    actor_user_id: UUID,
    request_id: UUID | None = None,
) -> RuleVersion:
    # 账本级别 advisory lock：避免两个管理员同时激活不同草稿。
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)"),
        {"key": f"rule-activation:{household_id}"},
    )
    rule = session.scalar(
        select(RuleVersion)
        .where(
            RuleVersion.id == rule_version_id,
            RuleVersion.household_id == household_id,
        )
        .with_for_update()
    )
    if rule is None:
        raise NotFoundError("规则版本不存在")
    if rule.status != "draft":
        raise ConflictError("规则不是草稿状态")
    if rule.row_version != expected_row_version:
        raise ConflictError("规则草稿已被修改，请重新加载", code="VERSION_CONFLICT")
    if not rule.preview_hash or rule.preview_hash != expected_preview_hash:
        raise ConflictError("规则预览已过期，请重新预览", code="RULE_PREVIEW_STALE")

    active = session.scalar(
        select(RuleVersion)
        .where(
            RuleVersion.household_id == household_id,
            RuleVersion.status == "active",
        )
        .with_for_update()
    )
    active_no = active.version_no if active else 0
    if active_no != expected_active_version_no:
        raise ConflictError("生效规则已变化，请重新预览", code="VERSION_CONFLICT")

    # 预览必须覆盖当前所有开放账期，且这些账期在预览后没有发生变化。
    preview = rule.preview_snapshot or {}
    preview_periods = {
        item["period_id"]: item.get("period_version") for item in preview.get("periods", [])
    }
    open_periods = list(
        session.scalars(
            select(BillingPeriod).where(
                BillingPeriod.household_id == household_id,
                BillingPeriod.status == "open",
            )
        )
    )
    if {str(period.id) for period in open_periods} != set(preview_periods):
        raise ConflictError("开放账期在预览后发生变化，请重新预览", code="RULE_PREVIEW_STALE")
    for period in open_periods:
        if preview_periods.get(str(period.id)) != period.version:
            raise ConflictError("账期数据在预览后发生变化，请重新预览", code="RULE_PREVIEW_STALE")

    if active is not None:
        active.status = "archived"
        active.archived_at = utcnow()
        # 先落库归档，避免同一 flush 中与新 active 的 partial unique 冲突。
        session.flush()
    rule.status = "active"
    rule.activated_by = actor_user_id
    rule.activated_at = utcnow()
    rule.supersedes_id = active.id if active else None
    session.flush()

    payload = to_payload(rule, load_items(session, rule.id))
    for period in open_periods:
        allocations.reallocate_period(session, period, payload)
        period.version += 1
        period.updated_at = utcnow()
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="rule.activate",
        entity_type="rule_version",
        entity_id=rule.id,
        after={
            "version_no": rule.version_no,
            "config_hash": rule.config_hash,
            "open_periods": [period.period_key for period in open_periods],
        },
        request_id=request_id,
    )
    return rule


def list_versions(session: Session, household_id: UUID) -> list[RuleVersion]:
    return list(
        session.scalars(
            select(RuleVersion)
            .where(RuleVersion.household_id == household_id)
            .order_by(RuleVersion.version_no.desc())
        )
    )


def snapshot(session: Session, rule: RuleVersion) -> dict[str, Any]:
    items = load_items(session, rule.id)
    return {
        "rule_version_id": str(rule.id),
        "version_no": rule.version_no,
        "config_hash": rule.config_hash,
        "owner_person_id": str(rule.remainder_owner_person_id),
        "items": [
            {
                "category": item.category,
                "split_method": item.split_method,
                "fallback_method": item.fallback_method,
            }
            for item in items
        ],
    }
