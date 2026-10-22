"""模型 Provider 单元测试。"""

from __future__ import annotations

import httpx
import pytest

from roommate_billing.agent.providers import (
    DisabledProvider,
    OpenAICompatibleProvider,
    build_provider,
)
from roommate_billing.agent.types import (
    AgentUnavailableError,
    Message,
    ProviderError,
    ToolCall,
)
from roommate_billing.config import Settings


class _Response:
    def __init__(self, payload, *, status_error: bool = False) -> None:
        self._payload = payload
        self.headers = {"x-request-id": "req-1"}
        self.status_error = status_error

    def raise_for_status(self) -> None:
        if self.status_error:
            raise httpx.HTTPError("boom")

    def json(self):
        return self._payload


def test_disabled_provider_raises() -> None:
    with pytest.raises(AgentUnavailableError):
        DisabledProvider().complete(messages=[], tools=[])


def test_build_provider(monkeypatch) -> None:
    monkeypatch.setenv("LLM_ENABLED", "false")
    assert isinstance(build_provider(Settings()), DisabledProvider)
    enabled = Settings(llm_enabled=True, llm_api_key="secret")
    assert isinstance(build_provider(enabled), OpenAICompatibleProvider)


def test_openai_provider_parses_tool_calls(monkeypatch) -> None:
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return _Response(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "function": {
                                        "name": "create_bill",
                                        "arguments": '{"amount_cents": 100}',
                                    },
                                }
                            ],
                        }
                    }
                ],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }
        )

    monkeypatch.setattr("roommate_billing.agent.providers.httpx.post", fake_post)
    provider = OpenAICompatibleProvider(
        base_url="https://llm.example/v1/", api_key="secret", model="m"
    )
    response = provider.complete(
        messages=[
            Message(role="system", content="sys"),
            Message(
                role="assistant",
                content=None,
                tool_calls=[ToolCall(id="old", name="read", arguments={"a": 1})],
            ),
            Message(role="tool", content='{"ok":true}', tool_call_id="old", name="read"),
        ],
        tools=[{"type": "function", "function": {"name": "create_bill"}}],
    )
    assert response.content is None
    assert response.tool_calls[0].name == "create_bill"
    assert response.tool_calls[0].arguments == {"amount_cents": 100}
    assert response.input_tokens == 11
    assert response.output_tokens == 7
    assert captured["url"] == "https://llm.example/v1/chat/completions"
    assert captured["json"]["model"] == "m"
    assert captured["json"]["messages"][1]["tool_calls"][0]["function"]["name"] == "read"
    assert captured["json"]["messages"][2]["tool_call_id"] == "old"


def test_openai_provider_rejects_bad_arguments_and_http_errors(monkeypatch) -> None:
    bad = _Response(
        {
            "choices": [
                {
                    "message": {
                        "content": "x",
                        "tool_calls": [{"id": "c", "function": {"name": "x", "arguments": "{"}}],
                    }
                }
            ]
        }
    )
    monkeypatch.setattr("roommate_billing.agent.providers.httpx.post", lambda *args, **kwargs: bad)
    provider = OpenAICompatibleProvider(base_url="https://llm.example/v1", api_key="k", model="m")
    with pytest.raises(ProviderError):
        provider.complete(messages=[], tools=[])

    failing = _Response({}, status_error=True)
    monkeypatch.setattr(
        "roommate_billing.agent.providers.httpx.post", lambda *args, **kwargs: failing
    )
    with pytest.raises(ProviderError):
        provider.complete(messages=[], tools=[])

    malformed = _Response({"choices": []})
    monkeypatch.setattr(
        "roommate_billing.agent.providers.httpx.post", lambda *args, **kwargs: malformed
    )
    with pytest.raises(ProviderError):
        provider.complete(messages=[], tools=[])
