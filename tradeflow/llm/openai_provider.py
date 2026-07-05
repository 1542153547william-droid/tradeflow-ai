"""OpenAI-compatible provider.

Talks to any chat-completions API that speaks the OpenAI wire format. We use it
for Alibaba Bailian / DashScope (Qwen models), whose compatible endpoint is
`https://dashscope.aliyuncs.com/compatible-mode/v1` and is reachable directly
from mainland China — no overseas relay needed. The same class works for any
other OpenAI-compatible backend by changing `base_url` / model.

Interface parallels AnthropicProvider; the agent loop doesn't care which one it
gets.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import (
    LLMProvider,
    LLMResponse,
    Message,
    ModelConfig,
    Role,
    StopReason,
    ToolCall,
)


class OpenAICompatProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None,
                 config: Optional[ModelConfig] = None,
                 base_url: Optional[str] = None) -> None:
        super().__init__(config)
        self._api_key = api_key
        self._base_url = base_url
        self._client = None  # lazily constructed

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "openai SDK not installed. `pip install openai`."
            ) from exc
        if not self._api_key:
            raise RuntimeError(
                "No API key configured. Set DASHSCOPE_API_KEY (Bailian) or the "
                "matching provider key before using OpenAICompatProvider."
            )
        kwargs: Dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        self._client = OpenAI(**kwargs)

    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
    ) -> LLMResponse:
        self._ensure_client()
        wire: List[Dict[str, Any]] = []
        if system:
            wire.append({"role": "system", "content": system})
        for m in messages:
            wire.extend(self._to_wire(m))

        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": wire,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if tools:
            kwargs["tools"] = [self._tool_to_wire(t) for t in tools]
        kwargs.update(self.config.extra.get("api_kwargs", {}))

        resp = self._client.chat.completions.create(**kwargs)
        return self._from_wire(resp)

    # --- translation helpers ------------------------------------------------
    def _to_wire(self, m: Message) -> List[Dict[str, Any]]:
        if m.role == Role.TOOL:
            return [
                {"role": "tool", "tool_call_id": r.tool_call_id, "content": r.content}
                for r in m.tool_results
            ]
        if m.role == Role.ASSISTANT:
            d: Dict[str, Any] = {"role": "assistant", "content": m.content or None}
            if m.tool_calls:
                d["tool_calls"] = [{
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                } for tc in m.tool_calls]
            return [d]
        role = "user" if m.role == Role.USER else "system"
        return [{"role": role, "content": m.content}]

    def _tool_to_wire(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec.get("description", ""),
                "parameters": spec["input_schema"],
            },
        }

    def _from_wire(self, resp: Any) -> LLMResponse:
        choice = resp.choices[0]
        msg = choice.message
        tool_calls: List[ToolCall] = []
        for tc in (getattr(msg, "tool_calls", None) or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        stop = StopReason.TOOL_USE if tool_calls else StopReason.END
        if choice.finish_reason == "length":
            stop = StopReason.MAX_TOKENS
        return LLMResponse(
            text=msg.content or "",
            tool_calls=tool_calls,
            stop_reason=stop,
            raw=resp,
        )
