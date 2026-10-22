"""账单与分摊 API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...schemas.api import BillCreate, BillUpdate, BillVoid, SplitPreviewRequest
from ...services import bills, idempotency
from ..deps import (
    Principal,
    ensure_household,
    get_current_principal,
    get_db,
    get_request_id,
    require_admin,
    require_idempotency_key,
)
from ..serializers import allocation_payload, bill_payload

router = APIRouter(prefix="/api/v1", tags=["bills"])


@router.get("/households/{household_id}/periods/{period_id}/bills")
def list_bills(
    household_id: UUID,
    period_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    rows = bills.list_bills(session, household_id, period_id)
    return {"data": {"items": [bill_payload(session, row) for row in rows]}}


@router.post("/households/{household_id}/periods/{period_id}/bills", status_code=201)
def create_bill(
    household_id: UUID,
    period_id: UUID,
    body: BillCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
    idempotency_key: str = Depends(require_idempotency_key),
) -> JSONResponse:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)

    def action() -> tuple[int, dict]:
        bill = bills.create_bill(
            session,
            household_id=household_id,
            period_id=period_id,
            actor_user_id=principal.user_id,
            category=body.category,
            name=body.name,
            amount_cents=body.amount_cents,
            incurred_on=body.incurred_on,
            request_id=request_id,
        )
        return 201, {"data": bill_payload(session, bill)}

    status_code, payload = idempotency.execute_idempotent(
        session,
        actor_user_id=principal.user_id,
        household_id=household_id,
        scope=f"create_bill:{period_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        action=action,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/households/{household_id}/bills/{bill_id}")
def get_bill(
    household_id: UUID,
    bill_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    return {"data": bill_payload(session, bills.get_bill(session, household_id, bill_id))}


@router.patch("/households/{household_id}/bills/{bill_id}")
def update_bill(
    household_id: UUID,
    bill_id: UUID,
    body: BillUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    bill = bills.update_bill(
        session,
        household_id=household_id,
        bill_id=bill_id,
        actor_user_id=principal.user_id,
        expected_version=body.expected_version,
        name=body.name,
        amount_cents=body.amount_cents,
        incurred_on=body.incurred_on,
        request_id=request_id,
    )
    return {"data": bill_payload(session, bill)}


@router.post("/households/{household_id}/bills/{bill_id}/void")
def void_bill(
    household_id: UUID,
    bill_id: UUID,
    body: BillVoid,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
    idempotency_key: str = Depends(require_idempotency_key),
) -> JSONResponse:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)

    def action() -> tuple[int, dict]:
        bill = bills.void_bill(
            session,
            household_id=household_id,
            bill_id=bill_id,
            actor_user_id=principal.user_id,
            expected_version=body.expected_version,
            reason=body.reason,
            request_id=request_id,
        )
        return 200, {"data": bill_payload(session, bill)}

    status_code, payload = idempotency.execute_idempotent(
        session,
        actor_user_id=principal.user_id,
        household_id=household_id,
        scope=f"void_bill:{bill_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        action=action,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/households/{household_id}/bills/{bill_id}/allocations")
def get_allocations(
    household_id: UUID,
    bill_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    rows = bills.get_allocations(session, household_id, bill_id)
    return {"data": {"items": [allocation_payload(row) for row in rows]}}


@router.post("/households/{household_id}/periods/{period_id}/split-preview")
def split_preview(
    household_id: UUID,
    period_id: UUID,
    body: SplitPreviewRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    data = bills.split_preview(
        session,
        household_id=household_id,
        period_id=period_id,
        rule_version_id=body.rule_version_id,
        occupancies=[item.model_dump() for item in body.occupancies]
        if body.occupancies is not None
        else None,
        bills=[item.model_dump() for item in body.bills] if body.bills is not None else None,
    )
    return {"data": data}
