"""Agent 会话 API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...agent.loop import AgentService
from ...schemas.api import AgentMessageCreate, ConversationCreate, ConversationUpdate
from ..deps import (
    Principal,
    ensure_household,
    get_current_principal,
    get_db,
    get_llm_provider,
)
from ..serializers import (
    agent_message_payload,
    conversation_payload,
    pending_action_payload,
)

router = APIRouter(prefix="/api/v1", tags=["agent"])


@router.get("/households/{household_id}/agent/conversations")
def list_conversations(
    household_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    service = AgentService(session)
    rows = service.list_conversations(principal, household_id)
    return {"data": {"items": [conversation_payload(row) for row in rows]}}


@router.post("/households/{household_id}/agent/conversations", status_code=201)
def create_conversation(
    household_id: UUID,
    body: ConversationCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    service = AgentService(session)
    conversation = service.create_conversation(principal, household_id, body.title)
    return {"data": conversation_payload(conversation)}


@router.get("/households/{household_id}/agent/conversations/{conversation_id}")
def get_conversation(
    household_id: UUID,
    conversation_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    service = AgentService(session)
    conversation = service.get_conversation(principal, household_id, conversation_id)
    messages = service.list_messages(principal, household_id, conversation_id)
    return {
        "data": {
            "conversation": conversation_payload(conversation),
            "messages": [agent_message_payload(row) for row in messages],
        }
    }


@router.get("/households/{household_id}/agent/conversations/{conversation_id}/messages")
def list_messages(
    household_id: UUID,
    conversation_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    service = AgentService(session)
    rows = service.list_messages(principal, household_id, conversation_id)
    return {"data": {"items": [agent_message_payload(row) for row in rows]}}


@router.post("/households/{household_id}/agent/conversations/{conversation_id}/messages")
def send_message(
    household_id: UUID,
    conversation_id: UUID,
    body: AgentMessageCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
    provider=Depends(get_llm_provider),
) -> dict:
    ensure_household(principal, household_id)
    service = AgentService(session)
    return {
        "data": service.send_message(
            principal,
            household_id,
            conversation_id,
            content=body.content,
            provider=provider,
            client_message_id=body.client_message_id,
        )
    }


@router.get("/households/{household_id}/agent/conversations/{conversation_id}/actions")
def list_actions(
    household_id: UUID,
    conversation_id: UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    service = AgentService(session)
    rows = service.list_actions(principal, household_id, conversation_id)
    return {"data": {"items": [pending_action_payload(row) for row in rows]}}


@router.patch("/households/{household_id}/agent/conversations/{conversation_id}")
def update_conversation(
    household_id: UUID,
    conversation_id: UUID,
    body: ConversationUpdate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db),
) -> dict:
    ensure_household(principal, household_id)
    service = AgentService(session)
    conversation = service.update_conversation(
        principal,
        household_id,
        conversation_id,
        title=body.title,
        archived=body.archived,
    )
    return {"data": conversation_payload(conversation)}
