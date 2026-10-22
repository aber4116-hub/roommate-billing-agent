"""结算 API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session

from ...schemas.api import SettlementCreate
from ...services import idempotency, settlements
from ..deps import (
    Principal,
    ensure_household,
    get_current_principal,
    get_db,
    get_request_id,
    require_admin,
    require_idempotency_key,
)
from ..serializers import settlement_payload

router = APIRouter(prefix="/api/v1", tags=["settlements"])


@router.get("/households/{household_id}/periods/{period_id}/settlement-preview")
def preview_settlement(
    household_id: UUID,
    period_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    return {"data": settlements.preview(session, household_id=household_id, period_id=period_id)}


@router.post("/households/{household_id}/periods/{period_id}/settlements", status_code=201)
def create_settlement(
    household_id: UUID,
    period_id: UUID,
    body: SettlementCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
    idempotency_key: str = Depends(require_idempotency_key),
) -> JSONResponse:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)

    def action() -> tuple[int, dict]:
        settlement, lines = settlements.create_settlement(
            session,
            household_id=household_id,
            period_id=period_id,
            actor_user_id=principal.user_id,
            expected_period_version=body.expected_period_version,
            expected_preview_hash=body.preview_hash,
            note=body.note,
            request_id=request_id,
        )
        return 201, {"data": settlement_payload(settlement, lines)}

    status_code, payload = idempotency.execute_idempotent(
        session,
        actor_user_id=principal.user_id,
        household_id=household_id,
        scope=f"create_settlement:{period_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        action=action,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/households/{household_id}/periods/{period_id}/settlements")
def list_settlements(
    household_id: UUID,
    period_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    rows = settlements.list_settlements(session, household_id, period_id)
    return {"data": {"items": [settlement_payload(row) for row in rows]}}


@router.get("/households/{household_id}/settlements/{settlement_id}")
def get_settlement(
    household_id: UUID,
    settlement_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    settlement = settlements.get_settlement(session, household_id, settlement_id)
    return {"data": settlement_payload(settlement, settlements.lines_of(session, settlement.id))}


@router.get("/households/{household_id}/settlements/{settlement_id}/explain")
def explain_settlement(
    household_id: UUID,
    settlement_id: UUID,
    person_id: UUID = Query(...),
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    return {
        "data": settlements.explain(
            session,
            household_id=household_id,
            settlement_id=settlement_id,
            person_id=person_id,
        )
    }


@router.get("/households/{household_id}/settlements/{settlement_id}/export")
def export_settlement(
    household_id: UUID,
    settlement_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> PlainTextResponse:
    ensure_household(principal, household_id)
    filename, content = settlements.export_csv(
        session, household_id=household_id, settlement_id=settlement_id
    )
    return PlainTextResponse(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
