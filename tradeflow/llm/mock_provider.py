"""A deterministic, no-network provider.

Lets us exercise the full agent loop (reasoning -> tool_call -> observe -> answer)
today, before any real API key exists. Two ways to drive it:

* Pass a `script`: a list of LLMResponse objects returned in order. Best for tests.
* Otherwise it uses a tiny built-in heuristic: if a `calculator`/`add`-style tool
  is available and the prompt looks arithmetic, it calls it once, then answers.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .base import (
    LLMProvider,
    LLMResponse,
    Message,
    Role,
    StopReason,
    ToolCall,
)


class MockProvider(LLMProvider):
    def __init__(self, script: Optional[List[LLMResponse]] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._script = list(script or [])
        self._step = 0

    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
    ) -> LLMResponse:
        if self._script:
            resp = self._script[min(self._step, len(self._script) - 1)]
            self._step += 1
            return resp
        return self._heuristic(messages, tools or [])

    # --- built-in heuristic so the demo is self-contained -------------------
    def _heuristic(self, messages: List[Message], tools: List[Dict[str, Any]]) -> LLMResponse:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == Role.USER), ""
        )
        already_used_tool = any(m.role == Role.TOOL for m in messages)
        tool_names = {t["name"] for t in tools}

        match = re.search(r"(-?\d+)\s*([+\-*/])\s*(-?\d+)", last_user)
        if match and not already_used_tool and "calculator" in tool_names:
            a, op, b = match.group(1), match.group(2), match.group(3)
            return LLMResponse(
                reasoning=f"The user asked to compute {a}{op}{b}. I'll use the calculator tool.",
                stop_reason=StopReason.TOOL_USE,
                tool_calls=[ToolCall(
                    id="call_1",
                    name="calculator",
                    arguments={"expression": f"{a}{op}{b}"},
                )],
            )

        if already_used_tool:
            tool_out = next(
                (r.content for m in reversed(messages) for r in m.tool_results),
                "",
            )
            return LLMResponse(
                reasoning="I have the tool result; I can answer now.",
                text=f"The result is {tool_out}.",
                stop_reason=StopReason.END,
            )

        return LLMResponse(
            reasoning="No tool needed for this request.",
            text=f"[mock] I received: {last_user!r}. (Wire up a real provider to get real answers.)",
            stop_reason=StopReason.END,
        )
