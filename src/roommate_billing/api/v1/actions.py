"""Agent 待确认动作 API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...schemas.api import ActionConfirm
from ...services import actions, idempotency
from ..deps import (
    Principal,
    ensure_household,
    get_current_principal,
    get_db,
    get_request_id,
    require_idempotency_key,
)
from ..serializers import pending_action_payload

router = APIRouter(prefix="/api/v1", tags=["actions"])


@router.get("/households/{household_id}/actions/{action_id}")
def get_action(
    household_id: UUID,
    action_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    action = actions.get_action(
        session, household_id=household_id, action_id=action_id, principal=principal
    )
    return {"data": pending_action_payload(action)}


@router.post("/households/{household_id}/actions/{action_id}/confirm")
def confirm_action(
    household_id: UUID,
    action_id: UUID,
    body: ActionConfirm,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
    idempotency_key: str = Depends(require_idempotency_key),
) -> JSONResponse:
    ensure_household(principal, household_id)

    def action() -> tuple[int, dict]:
        action_type, result = actions.confirm_action(
            session,
            household_id=household_id,
            action_id=action_id,
            principal=principal,
            expected_payload_hash=body.expected_payload_hash,
            request_id=request_id,
        )
        return 200, {"data": {"action_type": action_type, "result": result}}

    status_code, payload = idempotency.execute_idempotent(
        session,
        actor_user_id=principal.user_id,
        household_id=household_id,
        scope=f"confirm_action:{action_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        action=action,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.post("/households/{household_id}/actions/{action_id}/cancel")
def cancel_action(
    household_id: UUID,
    action_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
) -> dict:
    ensure_household(principal, household_id)
    action = actions.cancel_action(
        session,
        household_id=household_id,
        action_id=action_id,
        principal=principal,
        request_id=request_id,
    )
    return {"data": pending_action_payload(action)}
