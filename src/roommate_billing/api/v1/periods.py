"""账期与入住天数 API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...schemas.api import OccupanciesUpdate, PeriodCreate, ReopenPeriod, VersionRequest
from ...services import allocations, periods
from ..deps import (
    Principal,
    ensure_household,
    get_current_principal,
    get_db,
    get_request_id,
    require_admin,
)
from ..serializers import period_payload

router = APIRouter(prefix="/api/v1", tags=["periods"])


@router.get("/households/{household_id}/periods")
def list_periods(
    household_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    return {
        "data": {
            "items": [period_payload(row) for row in periods.list_periods(session, household_id)]
        }
    }


@router.post("/households/{household_id}/periods", status_code=201)
def create_period(
    household_id: UUID,
    body: PeriodCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    period = periods.create_period(
        session,
        household_id=household_id,
        actor_user_id=principal.user_id,
        period_key=body.period_key,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        request_id=request_id,
    )
    return {"data": period_payload(period)}


@router.get("/households/{household_id}/periods/{period_id}")
def get_period(
    household_id: UUID,
    period_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    return {"data": period_payload(periods.get_period(session, household_id, period_id))}


@router.get("/households/{household_id}/periods/{period_id}/occupancies")
def get_occupancies(
    household_id: UUID,
    period_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    period = periods.get_period(session, household_id, period_id)
    mapping = periods.occupancy_map(session, period.id)
    people = allocations.load_active_people(session, household_id)
    return {
        "data": {
            "period_id": str(period.id),
            "items": [
                {
                    "person_id": str(person.id),
                    "display_name": person.display_name,
                    "days": mapping.get(person.id, 0),
                }
                for person in people
            ],
        }
    }


@router.put("/households/{household_id}/periods/{period_id}/occupancies")
def set_occupancies(
    household_id: UUID,
    period_id: UUID,
    body: OccupanciesUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    period = periods.set_occupancies(
        session,
        household_id=household_id,
        period_id=period_id,
        actor_user_id=principal.user_id,
        items=[item.model_dump() for item in body.items],
        expected_version=body.expected_version,
        request_id=request_id,
    )
    return {"data": period_payload(period)}


@router.post("/households/{household_id}/periods/{period_id}/lock")
def lock_period(
    household_id: UUID,
    period_id: UUID,
    body: VersionRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    period = periods.lock_period(
        session,
        household_id=household_id,
        period_id=period_id,
        actor_user_id=principal.user_id,
        expected_version=body.expected_version,
        request_id=request_id,
    )
    return {"data": period_payload(period)}


@router.post("/households/{household_id}/periods/{period_id}/reopen")
def reopen_period(
    household_id: UUID,
    period_id: UUID,
    body: ReopenPeriod,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    period = periods.reopen_period(
        session,
        household_id=household_id,
        period_id=period_id,
        actor_user_id=principal.user_id,
        expected_version=body.expected_version,
        reason=body.reason,
        request_id=request_id,
    )
    return {"data": period_payload(period)}
