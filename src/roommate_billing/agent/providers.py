"""模型 Provider 实现。"""

from __future__ import annotations

import json

import httpx

from ..config import Settings
from .types import AgentUnavailableError, LLMResponse, Message, ProviderError, ToolCall


class DisabledProvider:
    def complete(self, *, messages: list[Message], tools: list[dict]) -> LLMResponse:
        raise AgentUnavailableError("Agent 未启用或未配置模型 API")


class FakeProvider:
    """测试用：按脚本返回响应，并记录调用。"""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[list[Message], list[dict]]] = []

    def complete(self, *, messages: list[Message], tools: list[dict]) -> LLMResponse:
        self.calls.append((list(messages), list(tools)))
        if not self._responses:
            raise ProviderError("FakeProvider 没有更多脚本响应")
        return self._responses.pop(0)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _message_payload(self, message: Message) -> dict:
        payload: dict = {"role": message.role}
        if message.content is not None:
            payload["content"] = message.content
        if message.tool_call_id:
            payload["tool_call_id"] = message.tool_call_id
        if message.name:
            payload["name"] = message.name
        if message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    },
                }
                for call in message.tool_calls
            ]
        return payload

    def complete(self, *, messages: list[Message], tools: list[dict]) -> LLMResponse:
        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [self._message_payload(message) for message in messages],
                    "tools": tools,
                    "tool_choice": "auto",
                    "temperature": 0.2,
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"模型调用失败：{exc.__class__.__name__}") from exc

        try:
            choice = data["choices"][0]["message"]
            calls = []
            for call in choice.get("tool_calls") or []:
                function = call["function"]
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError as exc:
                    raise ProviderError("模型返回了非法工具参数") from exc
                if not isinstance(arguments, dict):
                    raise ProviderError("模型工具参数必须是对象")
                calls.append(
                    ToolCall(
                        id=call.get("id", ""),
                        name=function.get("name", ""),
                        arguments=arguments,
                    )
                )
            usage = data.get("usage") or {}
            return LLMResponse(
                content=choice.get("content"),
                tool_calls=calls,
                raw_request_id=response.headers.get("x-request-id"),
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("模型响应结构不合法") from exc


def build_provider(settings: Settings):
    if not settings.llm_enabled or not settings.llm_api_key:
        return DisabledProvider()
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
