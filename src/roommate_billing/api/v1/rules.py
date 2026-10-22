"""规则版本 API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ...schemas.api import RuleActivate, RuleDraftCreate
from ...services import idempotency, rules
from ..deps import (
    Principal,
    ensure_household,
    get_current_principal,
    get_db,
    get_request_id,
    require_admin,
    require_idempotency_key,
)
from ..serializers import rule_payload

router = APIRouter(prefix="/api/v1", tags=["rules"])


@router.get("/households/{household_id}/rule-versions")
def list_rules(
    household_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    rows = rules.list_versions(session, household_id)
    return {"data": {"items": [rule_payload(session, row) for row in rows]}}


@router.post("/households/{household_id}/rule-versions", status_code=201)
def create_draft(
    household_id: UUID,
    body: RuleDraftCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
    idempotency_key: str = Depends(require_idempotency_key),
) -> JSONResponse:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)

    def action() -> tuple[int, dict]:
        rule = rules.create_draft(
            session,
            household_id=household_id,
            owner_person_id=body.owner_person_id,
            items=[item.model_dump() for item in body.items],
            note=body.note,
            actor_user_id=principal.user_id,
            request_id=request_id,
        )
        return 201, {"data": rule_payload(session, rule)}

    status_code, payload = idempotency.execute_idempotent(
        session,
        actor_user_id=principal.user_id,
        household_id=household_id,
        scope="create_rule_draft",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        action=action,
    )
    return JSONResponse(status_code=status_code, content=payload)


@router.get("/households/{household_id}/rule-versions/{rule_version_id}")
def get_rule(
    household_id: UUID,
    rule_version_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    rule, _items = rules.get_rule(session, household_id, rule_version_id)
    return {"data": rule_payload(session, rule)}


@router.post("/households/{household_id}/rule-versions/{rule_version_id}/preview")
def preview_rule(
    household_id: UUID,
    rule_version_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    rule, preview = rules.preview_rule(
        session,
        household_id=household_id,
        rule_version_id=rule_version_id,
        actor_user_id=principal.user_id,
        request_id=request_id,
    )
    return {
        "data": {
            "rule": rule_payload(session, rule),
            "preview": preview,
            "preview_hash": rule.preview_hash,
        }
    }


@router.post("/households/{household_id}/rule-versions/{rule_version_id}/activate")
def activate_rule(
    household_id: UUID,
    rule_version_id: UUID,
    body: RuleActivate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
    idempotency_key: str = Depends(require_idempotency_key),
) -> JSONResponse:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)

    def action() -> tuple[int, dict]:
        rule = rules.activate_rule(
            session,
            household_id=household_id,
            rule_version_id=rule_version_id,
            expected_active_version_no=body.expected_active_version_no,
            expected_preview_hash=body.expected_preview_hash,
            expected_row_version=body.expected_row_version,
            actor_user_id=principal.user_id,
            request_id=request_id,
        )
        return 200, {"data": rule_payload(session, rule)}

    status_code, payload = idempotency.execute_idempotent(
        session,
        actor_user_id=principal.user_id,
        household_id=household_id,
        scope=f"activate_rule:{rule_version_id}",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        action=action,
    )
    return JSONResponse(status_code=status_code, content=payload)
