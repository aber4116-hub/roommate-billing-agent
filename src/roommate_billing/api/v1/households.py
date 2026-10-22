"""账本与人员 API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db.models import User
from ...schemas.api import (
    HouseholdCreate,
    InviteCreate,
    MemberUpdate,
    PersonCreate,
)
from ...services import auth, households, ledger
from ..deps import (
    Principal,
    ensure_household,
    get_current_principal,
    get_db,
    get_request_id,
    require_admin,
)
from ..serializers import invite_payload, member_payload, person_payload

router = APIRouter(prefix="/api/v1", tags=["households"])


@router.get("/households")
def list_households(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    rows = households.list_households(session, principal.user_id)
    return {
        "data": {
            "items": [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "currency": row.currency,
                    "timezone": row.timezone,
                    "status": row.status,
                }
                for row in rows
            ]
        }
    }


@router.post("/households", status_code=201)
def create_household(
    body: HouseholdCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
) -> dict:
    household = households.create_household(
        session,
        name=body.name,
        actor_user_id=principal.user_id,
        request_id=request_id,
    )
    return {
        "data": {
            "id": str(household.id),
            "name": household.name,
            "currency": household.currency,
            "timezone": household.timezone,
            "status": household.status,
            "version": household.version,
        }
    }


@router.get("/households/{household_id}")
def get_household(
    household_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    row = households.get_household(session, household_id)
    return {
        "data": {
            "id": str(row.id),
            "name": row.name,
            "currency": row.currency,
            "timezone": row.timezone,
            "status": row.status,
            "version": row.version,
        }
    }


@router.get("/households/{household_id}/people")
def list_people(
    household_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    rows = households.list_people(session, household_id)
    return {"data": {"items": [person_payload(row) for row in rows]}}


@router.post("/households/{household_id}/people", status_code=201)
def create_person(
    household_id: UUID,
    body: PersonCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    request_id: UUID = Depends(get_request_id),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    person = households.create_person(
        session,
        household_id=household_id,
        actor_user_id=principal.user_id,
        display_name=body.display_name,
        slug=body.slug,
        user_id=body.user_id,
        request_id=request_id,
    )
    return {"data": person_payload(person)}


@router.get("/households/{household_id}/ledger/current")
def current_ledger(
    household_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    return {"data": ledger.current_ledger(session, household_id)}


@router.get("/households/{household_id}/members")
def list_members(
    household_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    rows = auth.list_members(session, household_id)
    return {"data": {"items": [member_payload(member, user) for member, user in rows]}}


@router.patch("/households/{household_id}/members/{user_id}")
def update_member(
    household_id: UUID,
    user_id: UUID,
    body: MemberUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    member = auth.update_member(
        session,
        household_id=household_id,
        actor_user_id=principal.user_id,
        target_user_id=user_id,
        role=body.role,
        status=body.status,
    )
    user = session.get(User, user_id)
    return {"data": member_payload(member, user)}


@router.get("/households/{household_id}/invites")
def list_invites(
    household_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    rows = auth.list_invites(session, household_id)
    return {"data": {"items": [invite_payload(row) for row in rows]}}


@router.post("/households/{household_id}/invites", status_code=201)
def create_invite(
    household_id: UUID,
    body: InviteCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    require_admin(principal, household_id)
    invite, token = auth.create_invite(
        session,
        household_id=household_id,
        actor_user_id=principal.user_id,
        role=body.role,
        email=body.email,
    )
    data = invite_payload(invite)
    data["token"] = token
    return {"data": data}
