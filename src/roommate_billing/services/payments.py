"""实际收款与调整服务（只追加）。"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.base import utcnow
from ..db.models import BillingPeriod, Payment, Person
from ..domain.money import MAX_BILL_CENTS, validate_cents
from .audit import record_audit
from .errors import ConflictError, NotFoundError, ValidationError

METHODS = ("cash", "bank", "wechat", "alipay", "other")


def _get_period(
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


def _person(session: Session, household_id: UUID, person_id: UUID) -> Person:
    person = session.scalar(
        select(Person).where(
            Person.id == person_id,
            Person.household_id == household_id,
        )
    )
    if person is None:
        raise NotFoundError("人员不存在")
    return person


def get_payment(session: Session, household_id: UUID, payment_id: UUID) -> Payment:
    payment = session.scalar(
        select(Payment).where(
            Payment.id == payment_id,
            Payment.household_id == household_id,
        )
    )
    if payment is None:
        raise NotFoundError("付款记录不存在")
    return payment


def _bump_period(period: BillingPeriod) -> None:
    period.version += 1
    period.updated_at = utcnow()


def record_payment(
    session: Session,
    *,
    household_id: UUID,
    period_id: UUID,
    actor_user_id: UUID,
    person_id: UUID,
    amount_cents: int,
    paid_on: date,
    method: str = "other",
    reference: str | None = None,
    note: str | None = None,
    request_id: UUID | None = None,
) -> Payment:
    validate_cents(amount_cents, allow_negative=False, max_abs_cents=MAX_BILL_CENTS)
    if amount_cents <= 0:
        raise ValidationError("付款金额必须大于 0")
    if method not in METHODS:
        raise ValidationError("未知付款方式")
    if len(reference or "") > 120:
        raise ValidationError("付款参考号过长")
    if len(note or "") > 500:
        raise ValidationError("备注过长")
    _person(session, household_id, person_id)
    period = _get_period(session, household_id, period_id, for_update=True)
    if period.status == "settled":
        raise ConflictError("已结算账期不能直接登记付款，请先重开", code="PERIOD_SETTLED")

    payment = Payment(
        household_id=household_id,
        period_id=period.id,
        person_id=person_id,
        amount_cents=amount_cents,
        kind="payment",
        method=method,
        paid_on=paid_on,
        reference=reference,
        note=note,
        created_by=actor_user_id,
    )
    session.add(payment)
    session.flush()
    _bump_period(period)
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="payment.record",
        entity_type="payment",
        entity_id=payment.id,
        after=payment_snapshot(payment),
        request_id=request_id,
    )
    return payment


def adjust_payment(
    session: Session,
    *,
    household_id: UUID,
    original_payment_id: UUID,
    actor_user_id: UUID,
    amount_cents: int,
    reason: str,
    request_id: UUID | None = None,
) -> Payment:
    original = get_payment(session, household_id, original_payment_id)
    if original.kind != "payment":
        raise ConflictError("只能对原始付款做调整")
    if amount_cents == 0:
        raise ValidationError("调整金额不能为 0")
    if abs(amount_cents) > abs(original.amount_cents):
        raise ValidationError("调整金额不能超过原付款金额")
    if not reason or len(reason) > 300:
        raise ValidationError("调整原因长度必须为 1–300")
    period = _get_period(session, household_id, original.period_id, for_update=True)
    if period.status == "settled":
        raise ConflictError("已结算账期不能直接调整付款，请先重开", code="PERIOD_SETTLED")

    existing_total = (
        session.scalar(
            select(func.coalesce(func.sum(Payment.amount_cents), 0)).where(
                Payment.adjusts_payment_id == original.id
            )
        )
        or 0
    )
    if abs(existing_total + amount_cents) > abs(original.amount_cents):
        raise ValidationError("累计调整金额不能超过原付款金额")

    adjustment = Payment(
        household_id=household_id,
        period_id=original.period_id,
        person_id=original.person_id,
        amount_cents=amount_cents,
        kind="adjustment",
        method="other",
        paid_on=original.paid_on,
        reference=original.reference,
        note=reason,
        adjusts_payment_id=original.id,
        created_by=actor_user_id,
    )
    session.add(adjustment)
    session.flush()
    _bump_period(period)
    session.flush()
    record_audit(
        session,
        household_id=household_id,
        actor_user_id=actor_user_id,
        action="payment.adjust",
        entity_type="payment",
        entity_id=adjustment.id,
        before=payment_snapshot(original),
        after=payment_snapshot(adjustment),
        request_id=request_id,
    )
    return adjustment


def payment_snapshot(payment: Payment) -> dict[str, Any]:
    return {
        "payment_id": str(payment.id),
        "period_id": str(payment.period_id),
        "person_id": str(payment.person_id),
        "amount_cents": payment.amount_cents,
        "kind": payment.kind,
        "method": payment.method,
        "paid_on": payment.paid_on.isoformat(),
        "adjusts_payment_id": str(payment.adjusts_payment_id)
        if payment.adjusts_payment_id
        else None,
    }


def list_payments(
    session: Session, household_id: UUID, period_id: UUID, *, person_id: UUID | None = None
) -> list[Payment]:
    statement = select(Payment).where(
        Payment.household_id == household_id,
        Payment.period_id == period_id,
    )
    if person_id is not None:
        statement = statement.where(Payment.person_id == person_id)
    return list(session.scalars(statement.order_by(Payment.recorded_at, Payment.id)))


def totals_by_person(session: Session, household_id: UUID, period_id: UUID) -> dict[UUID, int]:
    rows = session.execute(
        select(
            Payment.person_id,
            func.coalesce(func.sum(Payment.amount_cents), 0),
        )
        .where(
            Payment.household_id == household_id,
            Payment.period_id == period_id,
        )
        .group_by(Payment.person_id)
    )
    return {person_id: int(total) for person_id, total in rows}
