"""账期与入住天数服务。"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import BillingPeriod, Occupancy
from . import allocations, rules
from .audit import record_audit
from .errors import ConflictError, NotFoundError, ValidationError


def _month_bounds(period_key: str) -> tuple[date, date]:
    try:
        year_text, month_text = period_key.split("-", maxsplit=1)
        year, month = int(year_text), int(month_text)
        if len(year_text) != 4 or len(month_text) != 2 or not 1 <= month <= 12:
            raise ValueError
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)
    except (ValueError, TypeError) as exc:
        raise ValidationError("账期格式必须为 YYYY-MM") from exc


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


def list_periods(session: Session, household_id: UUID) -> list[BillingPeriod]:
    return list(
        session.scalars(
            select(BillingPeriod)
            .where(BillingPeriod.household_id == household_id)
            .order_by(BillingPeriod.period_key.desc())
        )
    )


def create_period(
    session: Session,
    *,
    household_id: UUID,
    actor_user_id: UUID,
    period_key: str,
    starts_on: date | None = None,
    ends_on: date | None = None,
    request_id: UUID | None = None,
) -> BillingPeriod:
    default_start, default_end = _month_bounds(period_key)
    start = starts_on or default_start
    end = ends_on or default_end
    if start > end:
        raise ValidationError("账期开始日期不能晚于结束日期")
    period = BillingPeriod(
        household_id=household_id,
        period_key=period_key,
        starts_on=start,
        ends_on=end,
        status="open",
        version=1,
        created_by=actor_user_id,
    )
    session.add(period)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ConflictError("该账期已存在") from exc
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="period.create",
        entity_type="billing_period",
        entity_id=period.id,
        after={"period_key": period_key, "starts_on": start, "ends_on": end},
        request_id=request_id,
    )
    return period


def current_period(session: Session, household_id: UUID) -> BillingPeriod | None:
    today = date.today()
    current = session.scalar(
        select(BillingPeriod)
        .where(
            BillingPeriod.household_id == household_id,
            BillingPeriod.status.in_(("open", "locked")),
            BillingPeriod.starts_on <= today,
            BillingPeriod.ends_on >= today,
        )
        .order_by(BillingPeriod.period_key.desc())
    )
    if current is not None:
        return current
    return session.scalar(
        select(BillingPeriod)
        .where(
            BillingPeriod.household_id == household_id,
            BillingPeriod.status.in_(("open", "locked")),
        )
        .order_by(BillingPeriod.period_key.desc())
    )


def occupancy_map(session: Session, period_id: UUID) -> dict[UUID, int]:
    return {
        row.person_id: row.days
        for row in session.scalars(select(Occupancy).where(Occupancy.period_id == period_id))
    }


def set_occupancies(
    session: Session,
    *,
    household_id: UUID,
    period_id: UUID,
    actor_user_id: UUID,
    items: list[dict[str, Any]],
    expected_version: int,
    request_id: UUID | None = None,
) -> BillingPeriod:
    period = get_period(session, household_id, period_id, for_update=True)
    if period.status != "open":
        raise ConflictError("只有开放账期可以修改入住天数", code="PERIOD_NOT_OPEN")
    if period.version != expected_version:
        raise ConflictError("账期已被其他人修改，请刷新后重试", code="VERSION_CONFLICT")

    people = allocations.load_active_people(session, household_id)
    people_by_id = {person.id: person for person in people}
    seen: set[UUID] = set()
    normalized: list[tuple[UUID, int]] = []
    for item in items:
        person_id = item["person_id"]
        days = item["days"]
        if person_id in seen:
            raise ValidationError("同一人员不能重复设置入住天数")
        if person_id not in people_by_id:
            raise ValidationError("入住人员不属于本账本或已停用")
        if isinstance(days, bool) or not isinstance(days, int) or not 0 <= days <= 31:
            raise ValidationError("入住天数必须是 0–31 的整数")
        seen.add(person_id)
        normalized.append((person_id, days))

    before = occupancy_map(session, period.id)
    for person_id, days in normalized:
        row = session.get(Occupancy, (period.id, person_id))
        if row is None:
            session.add(
                Occupancy(
                    household_id=household_id,
                    period_id=period.id,
                    person_id=person_id,
                    days=days,
                )
            )
        else:
            row.days = days
            row.updated_at = utcnow()
    session.flush()

    # 入住天数影响按天分摊的账单，必须在同一事务内重算所有开放账单。
    payload = rules.active_payload(session, household_id)
    allocations.reallocate_period(session, period, payload, people=people)
    period.version += 1
    period.updated_at = utcnow()
    session.flush()

    after = occupancy_map(session, period.id)
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="period.occupancies_update",
        entity_type="billing_period",
        entity_id=period.id,
        before={str(key): value for key, value in before.items()},
        after={str(key): value for key, value in after.items()},
        request_id=request_id,
    )
    return period


def lock_period(
    session: Session,
    *,
    household_id: UUID,
    period_id: UUID,
    actor_user_id: UUID,
    expected_version: int,
    request_id: UUID | None = None,
) -> BillingPeriod:
    period = get_period(session, household_id, period_id, for_update=True)
    if period.status != "open":
        raise ConflictError("只有开放账期可以锁定", code="PERIOD_NOT_OPEN")
    if period.version != expected_version:
        raise ConflictError("账期已被其他人修改，请刷新后重试", code="VERSION_CONFLICT")
    period.status = "locked"
    period.locked_at = utcnow()
    period.version += 1
    period.updated_at = utcnow()
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="period.lock",
        entity_type="billing_period",
        entity_id=period.id,
        after={"period_key": period.period_key, "version": period.version},
        request_id=request_id,
    )
    return period


def reopen_period(
    session: Session,
    *,
    household_id: UUID,
    period_id: UUID,
    actor_user_id: UUID,
    expected_version: int,
    reason: str,
    request_id: UUID | None = None,
) -> BillingPeriod:
    period = get_period(session, household_id, period_id, for_update=True)
    if period.status not in {"locked", "settled"}:
        raise ConflictError("只有已锁定/已结算账期可以重开", code="PERIOD_NOT_OPEN")
    if period.version != expected_version:
        raise ConflictError("账期已被其他人修改，请刷新后重试", code="VERSION_CONFLICT")
    if not reason or len(reason) > 300:
        raise ValidationError("重开原因长度必须为 1–300")
    before = {"status": period.status, "version": period.version}
    period.status = "open"
    period.locked_at = None
    period.settled_at = None
    period.version += 1
    period.updated_at = utcnow()
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="period.reopen",
        entity_type="billing_period",
        entity_id=period.id,
        before=before,
        after={"status": "open", "reason": reason},
        request_id=request_id,
    )
    return period
