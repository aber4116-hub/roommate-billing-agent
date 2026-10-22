"""Agent 工具循环、待确认动作、确认幂等与降级测试。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from roommate_billing.agent.providers import FakeProvider
from roommate_billing.agent.types import LLMResponse, ToolCall
from roommate_billing.api.deps import get_llm_provider
from roommate_billing.db.models import Bill, PendingAction, RuleVersion, Settlement
from roommate_billing.services import periods


def _create_conversation(client, household_id):
    response = client.post(
        f"/api/v1/households/{household_id}/agent/conversations",
        json={"title": "测试对话"},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _send(client, household_id, conversation_id, content: str):
    return client.post(
        f"/api/v1/households/{household_id}/agent/conversations/{conversation_id}/messages",
        json={"content": content},
    )


def _bill_count(db_session: Session, household_id) -> int:
    return db_session.scalar(
        select(func.count()).select_from(Bill).where(Bill.household_id == household_id)
    )


def test_agent_creates_pending_action_and_confirm_is_idempotent(
    client, seed, db_session: Session
) -> None:
    fake = FakeProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_create",
                        name="create_bill",
                        arguments={
                            "period_key": "2026-10",
                            "category": "electricity",
                            "name": "Agent 电费",
                            "amount_cents": 10000,
                        },
                    )
                ],
            ),
            LLMResponse(content="已准备新增电费，确认后才会入账。", tool_calls=[]),
        ]
    )
    client.app.dependency_overrides[get_llm_provider] = lambda: fake
    conversation_id = _create_conversation(client, seed.household_id)
    before = _bill_count(db_session, seed.household_id)

    response = _send(client, seed.household_id, conversation_id, "帮我录入 100 元电费")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pending_actions"], data
    assert data["tool_runs"][0]["status"] == "ok"
    assert _bill_count(db_session, seed.household_id) == before

    action = data["pending_actions"][0]
    listed = client.get(
        f"/api/v1/households/{seed.household_id}/agent/conversations/{conversation_id}/actions"
    )
    assert listed.status_code == 200
    assert len(listed.json()["data"]["items"]) == 1
    assert action["action_type"] == "create_bill"
    assert action["status"] == "pending"

    confirm = client.post(
        f"/api/v1/households/{seed.household_id}/actions/{action['id']}/confirm",
        json={"expected_payload_hash": action["payload_hash"]},
        headers={"Idempotency-Key": "confirm-1"},
    )
    assert confirm.status_code == 200, confirm.text
    assert _bill_count(db_session, seed.household_id) == before + 1

    replay = client.post(
        f"/api/v1/households/{seed.household_id}/actions/{action['id']}/confirm",
        json={"expected_payload_hash": action["payload_hash"]},
        headers={"Idempotency-Key": "confirm-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["data"] == confirm.json()["data"]
    assert _bill_count(db_session, seed.household_id) == before + 1

    new_key = client.post(
        f"/api/v1/households/{seed.household_id}/actions/{action['id']}/confirm",
        json={"expected_payload_hash": action["payload_hash"]},
        headers={"Idempotency-Key": "confirm-2"},
    )
    assert new_key.status_code == 200
    assert _bill_count(db_session, seed.household_id) == before + 1


def test_agent_does_not_expose_confirm_tool_and_handles_missing_args(
    client, seed, db_session: Session
) -> None:
    fake = FakeProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_bad",
                        name="confirm_rule_change",
                        arguments={"rule_version_id": str(uuid4())},
                    )
                ],
            ),
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_missing",
                        name="create_bill",
                        arguments={"category": "water", "name": "缺水"},
                    )
                ],
            ),
            LLMResponse(content="请提供金额；我不会直接改账。", tool_calls=[]),
        ]
    )
    client.app.dependency_overrides[get_llm_provider] = lambda: fake
    conversation_id = _create_conversation(client, seed.household_id)
    response = _send(client, seed.household_id, conversation_id, "随便录入")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["pending_actions"] == []
    assert data["tool_runs"][0]["result"]["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert data["tool_runs"][1]["result"]["error"]["code"] == "MISSING_ARGUMENT"
    assert _bill_count(db_session, seed.household_id) == 4

    # 模型上下文中只有白名单工具。
    _, tools = fake.calls[0]
    names = {item["function"]["name"] for item in tools}
    assert "confirm_rule_change" not in names
    assert "create_bill" in names


def test_agent_disabled_returns_503_and_core_still_works(client, seed) -> None:
    conversation_id = _create_conversation(client, seed.household_id)
    response = _send(client, seed.household_id, conversation_id, "你好")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AGENT_UNAVAILABLE"
    ledger = client.get(f"/api/v1/households/{seed.household_id}/ledger/current")
    assert ledger.status_code == 200


def test_agent_provider_failure_does_not_write(client, seed, db_session: Session) -> None:
    fake = FakeProvider([])
    client.app.dependency_overrides[get_llm_provider] = lambda: fake
    conversation_id = _create_conversation(client, seed.household_id)
    response = _send(client, seed.household_id, conversation_id, "帮我处理")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "AGENT_PROVIDER_ERROR"
    assert _bill_count(db_session, seed.household_id) == 4
    assert db_session.scalar(select(func.count()).select_from(PendingAction)) == 0


def test_member_cannot_confirm_admin_action(
    client, member_principal, seed, db_session: Session
) -> None:
    fake = FakeProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_member",
                        name="record_payment",
                        arguments={
                            "period_key": "2026-10",
                            "person_slug": "lin",
                            "amount_cents": 5000,
                            "paid_on": "2026-10-23",
                        },
                    )
                ],
            ),
            LLMResponse(content="已准备收款。", tool_calls=[]),
        ]
    )
    client.app.dependency_overrides[get_llm_provider] = lambda: fake
    conversation_id = _create_conversation(client, seed.household_id)
    response = _send(client, seed.household_id, conversation_id, "登记小林 50 元实收")
    assert response.status_code == 200, response.text
    action = response.json()["data"]["pending_actions"][0]
    assert action["action_type"] == "record_payment"

    # 成员不能确认 owner 创建的动作；这里用 owner 创建、成员确认的负向路径。
    from roommate_billing.api.deps import get_current_principal

    client.app.dependency_overrides[get_current_principal] = lambda: member_principal
    denied = client.post(
        f"/api/v1/households/{seed.household_id}/actions/{action['id']}/confirm",
        json={"expected_payload_hash": action["payload_hash"]},
        headers={"Idempotency-Key": "member-confirm"},
    )
    assert denied.status_code in (403, 404)
    assert db_session.scalar(select(func.count()).select_from(PendingAction)) == 1


def test_agent_settlement_action_confirm(client, seed, db_session: Session) -> None:
    period = periods.get_period(db_session, seed.household_id, seed.period_id)
    periods.lock_period(
        db_session,
        household_id=seed.household_id,
        period_id=period.id,
        actor_user_id=seed.user_id,
        expected_version=period.version,
        request_id=uuid4(),
    )
    db_session.commit()

    fake = FakeProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_settle",
                        name="create_settlement",
                        arguments={"period_key": "2026-10"},
                    )
                ],
            ),
            LLMResponse(content="已准备结算。", tool_calls=[]),
        ]
    )
    client.app.dependency_overrides[get_llm_provider] = lambda: fake
    conversation_id = _create_conversation(client, seed.household_id)
    response = _send(client, seed.household_id, conversation_id, "生成正式结算")
    assert response.status_code == 200, response.text
    action = response.json()["data"]["pending_actions"][0]
    assert action["action_type"] == "create_settlement"
    assert db_session.scalar(select(func.count()).select_from(Settlement)) == 0

    confirm = client.post(
        f"/api/v1/households/{seed.household_id}/actions/{action['id']}/confirm",
        json={"expected_payload_hash": action["payload_hash"]},
        headers={"Idempotency-Key": "settle-1"},
    )
    assert confirm.status_code == 200, confirm.text
    assert db_session.scalar(select(func.count()).select_from(Settlement)) == 1


def test_agent_rule_change_action_confirm(client, seed, db_session: Session) -> None:
    items = [
        {"category": category, "split_method": "equal_household"}
        for category in ("electricity", "water", "internet", "trash", "other")
    ]
    fake = FakeProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_rule",
                        name="propose_rule_change",
                        arguments={
                            "items": items,
                            "remainder_owner_slug": "zhou",
                            "note": "测试改为均摊",
                        },
                    )
                ],
            ),
            LLMResponse(content="规则草稿已准备。", tool_calls=[]),
        ]
    )
    client.app.dependency_overrides[get_llm_provider] = lambda: fake
    conversation_id = _create_conversation(client, seed.household_id)
    response = _send(client, seed.household_id, conversation_id, "把电费改成均摊")
    assert response.status_code == 200, response.text
    action = response.json()["data"]["pending_actions"][0]
    assert action["action_type"] == "confirm_rule_change"

    confirm = client.post(
        f"/api/v1/households/{seed.household_id}/actions/{action['id']}/confirm",
        json={"expected_payload_hash": action["payload_hash"]},
        headers={"Idempotency-Key": "rule-1"},
    )
    assert confirm.status_code == 200, confirm.text
    active = db_session.scalar(
        select(RuleVersion).where(
            RuleVersion.household_id == seed.household_id,
            RuleVersion.status == "active",
        )
    )
    assert active is not None
    assert active.version_no == 2


def test_agent_action_hash_mismatch_and_cancel(client, seed, db_session: Session) -> None:
    fake = FakeProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCall(
                        id="call_cancel",
                        name="create_bill",
                        arguments={
                            "period_key": "2026-10",
                            "category": "water",
                            "name": "待取消水费",
                            "amount_cents": 1200,
                        },
                    )
                ],
            ),
            LLMResponse(content="已准备。", tool_calls=[]),
        ]
    )
    client.app.dependency_overrides[get_llm_provider] = lambda: fake
    conversation_id = _create_conversation(client, seed.household_id)
    response = _send(client, seed.household_id, conversation_id, "新增水费")
    action = response.json()["data"]["pending_actions"][0]

    mismatch = client.post(
        f"/api/v1/households/{seed.household_id}/actions/{action['id']}/confirm",
        json={"expected_payload_hash": "0" * 64},
        headers={"Idempotency-Key": "mismatch"},
    )
    assert mismatch.status_code == 409

    cancelled = client.post(f"/api/v1/households/{seed.household_id}/actions/{action['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelled"

    after_cancel = client.post(
        f"/api/v1/households/{seed.household_id}/actions/{action['id']}/confirm",
        json={"expected_payload_hash": action["payload_hash"]},
        headers={"Idempotency-Key": "after-cancel"},
    )
    assert after_cancel.status_code == 409
    assert _bill_count(db_session, seed.household_id) == 4


def test_agent_duplicate_client_message_is_idempotent(client, seed) -> None:
    fake = FakeProvider([LLMResponse(content="收到。", tool_calls=[])])
    client.app.dependency_overrides[get_llm_provider] = lambda: fake
    conversation_id = _create_conversation(client, seed.household_id)
    body = {"content": "你好", "client_message_id": str(uuid4())}
    first = client.post(
        f"/api/v1/households/{seed.household_id}/agent/conversations/{conversation_id}/messages",
        json=body,
    )
    second = client.post(
        f"/api/v1/households/{seed.household_id}/agent/conversations/{conversation_id}/messages",
        json=body,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["message"]["id"] == second.json()["data"]["message"]["id"]
    assert len(fake.calls) == 1


def test_agent_max_steps_terminates(client, seed) -> None:
    fake = FakeProvider(
        [
            LLMResponse(
                content=None,
                tool_calls=[ToolCall(id=f"call_{index}", name="get_current_ledger", arguments={})],
            )
            for index in range(8)
        ]
    )
    client.app.dependency_overrides[get_llm_provider] = lambda: fake
    conversation_id = _create_conversation(client, seed.household_id)
    response = _send(client, seed.household_id, conversation_id, "一直查")
    assert response.status_code == 200, response.text
    assert "上限" in response.json()["data"]["message"]["content"]
    assert len(fake.calls) == 8


def test_agent_conversation_is_user_scoped(client, member_principal, seed) -> None:
    conversation_id = _create_conversation(client, seed.household_id)
    from roommate_billing.api.deps import get_current_principal

    client.app.dependency_overrides[get_current_principal] = lambda: member_principal
    response = client.get(
        f"/api/v1/households/{seed.household_id}/agent/conversations/{conversation_id}"
    )
    assert response.status_code == 404
