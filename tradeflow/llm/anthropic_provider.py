"""Anthropic (Claude) provider.

Interface is complete; real credentials/params are wired via `config.settings`
and can be filled in later. Requires the `anthropic` SDK and an API key at call
time — until then the harness runs fine on MockProvider.

Wire-format notes (Anthropic Messages API):
* `system` is a top-level parameter, not a message.
* assistant tool requests are `tool_use` content blocks; we send tool outputs
  back as `tool_result` blocks inside a user message.
"""

from __future__ import annotations

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


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None,
                 config: Optional[ModelConfig] = None,
                 base_url: Optional[str] = None,
                 proxy: Optional[str] = None) -> None:
        super().__init__(config)
        self._api_key = api_key
        # base_url: point at an overseas relay that forwards to Anthropic
        #   (common for mainland-China hosts that can't reach api.anthropic.com).
        # proxy: route the SDK's HTTPS calls through an http/socks proxy instead.
        # Use at most one; base_url is usually the more reliable of the two.
        self._base_url = base_url
        self._proxy = proxy
        self._client = None  # lazily constructed on first call

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            import anthropic  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "anthropic SDK not installed. `pip install anthropic` "
                "(or run on MockProvider until keys are ready)."
            ) from exc
        if not self._api_key:
            raise RuntimeError(
                "No Anthropic API key configured. Set ANTHROPIC_API_KEY "
                "(see config/settings.py) before using AnthropicProvider."
            )
        kwargs: Dict[str, Any] = {"api_key": self._api_key}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        if self._proxy:
            # anthropic SDK uses httpx under the hood; hand it a proxied client.
            import httpx  # type: ignore  (installed with anthropic)
            kwargs["http_client"] = httpx.Client(proxy=self._proxy)
        self._client = anthropic.Anthropic(**kwargs)

    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
    ) -> LLMResponse:
        self._ensure_client()
        kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "messages": [self._to_wire(m) for m in messages if m.role != Role.SYSTEM],
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools  # our spec already matches Anthropic's shape
        if self.config.thinking:
            kwargs["thinking"] = {"type": "enabled",
                                  "budget_tokens": self.config.extra.get("thinking_budget", 2048)}
        kwargs.update(self.config.extra.get("api_kwargs", {}))

        raw = self._client.messages.create(**kwargs)
        return self._from_wire(raw)

    # --- translation helpers ------------------------------------------------
    def _to_wire(self, m: Message) -> Dict[str, Any]:
        if m.role == Role.TOOL:
            content = [
                {
                    "type": "tool_result",
                    "tool_use_id": r.tool_call_id,
                    "content": r.content,
                    "is_error": r.is_error,
                }
                for r in m.tool_results
            ]
            return {"role": "user", "content": content}

        if m.role == Role.ASSISTANT and m.tool_calls:
            content: List[Dict[str, Any]] = []
            if m.content:
                content.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.name,
                    "input": tc.arguments,
                })
            return {"role": "assistant", "content": content}

        role = "assistant" if m.role == Role.ASSISTANT else "user"
        return {"role": role, "content": m.content}

    def _from_wire(self, raw: Any) -> LLMResponse:
        text_parts: List[str] = []
        reasoning: Optional[str] = None
        tool_calls: List[ToolCall] = []
        for block in getattr(raw, "content", []) or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(block.text)
            elif btype == "thinking":
                reasoning = getattr(block, "thinking", None)
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id, name=block.name, arguments=dict(block.input),
                ))
        stop = StopReason.TOOL_USE if tool_calls else StopReason.END
        if getattr(raw, "stop_reason", None) == "max_tokens":
            stop = StopReason.MAX_TOKENS
        return LLMResponse(
            text="".join(text_parts),
            reasoning=reasoning,
            tool_calls=tool_calls,
            stop_reason=stop,
            raw=raw,
        )
