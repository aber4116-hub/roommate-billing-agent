"""实际收款 API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...schemas.api import PaymentAdjust, PaymentCreate
from ...services import idempotency, payments
from ...services.errors import ForbiddenError
from ..deps import (
    Principal,
    ensure_household,
    get_current_principal,
    get_db,
    get_request_id,
    require_admin,
    require_idempotency_key,
)
from ..serializers import payment_payload

router = APIRouter(prefix="/api/v1", tags=["payments"])


@router.get("/households/{household_id}/periods/{period_id}/payments")
def list_payments(
    household_id: UUID,
    period_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    rows = payments.list_payments(session, household_id, period_id)
    return {"data": {"items": [payment_payload(row) for row in rows]}}


@router.post("/households/{household_id}/periods/{period_id}/payments", status_code=201)
def record_payment(
    household_id: UUID,
    period_id: UUID,
    body: PaymentCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
    idempotency_key: str = Depends(require_idempotency_key),
) -> JSONResponse:
    ensure_household(principal, household_id)
    if (
        principal.role_for(household_id) == "member"
        and principal.person_for(household_id) != body.person_id
    ):
        raise ForbiddenError("普通成员只能登记自己的付款")

    def action() -> tuple[int, dict]:
        payment = payments.record_payment(
            session,
            household_id=household_id,
            period_id=period_id,
            actor_user_id=principal.user_id,
            person_id=body.person_id,
            amount_cents=body.amount_cents,
            paid_on=body.paid_on,
            method=body.method,
            reference=body.reference,
            note=body.note,
            request_id=request_id,
        )
        return 201, {"data": payment_payload(payment)}

    status_code, payload = idempotency.execute_idempotent(
        session,
        actor_user_id=principal.user_id,
        household_id=household_id,
        scope=f"create_payment:{period_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        action=action,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/households/{household_id}/payments/{payment_id}")
def get_payment(
    household_id: UUID,
    payment_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    return {"data": payment_payload(payments.get_payment(session, household_id, payment_id))}


@router.post("/households/{household_id}/payments/{payment_id}/adjustments", status_code=201)
def adjust_payment(
    household_id: UUID,
    payment_id: UUID,
    body: PaymentAdjust,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
    idempotency_key: str = Depends(require_idempotency_key),
) -> JSONResponse:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)

    def action() -> tuple[int, dict]:
        payment = payments.adjust_payment(
            session,
            household_id=household_id,
            original_payment_id=payment_id,
            actor_user_id=principal.user_id,
            amount_cents=body.amount_cents,
            reason=body.reason,
            request_id=request_id,
        )
        return 201, {"data": payment_payload(payment)}

    status_code, payload = idempotency.execute_idempotent(
        session,
        actor_user_id=principal.user_id,
        household_id=household_id,
        scope=f"adjust_payment:{payment_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        action=action,
    )
    return JSONResponse(status_code=status_code, content=payload)
