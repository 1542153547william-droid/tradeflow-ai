"""The agent loop.

One `Agent` = a system prompt + a set of tools + a model provider. `run()` drives
the reason -> act -> observe cycle:

    1. Send conversation + tool specs to the model.
    2. If the model returns a final answer, stop and return it.
    3. If it requests tools, execute each, append the results, and loop.
    4. Bail out after `max_iterations` to guard against runaway loops.

The loop is provider-agnostic: it only depends on `LLMProvider` and `ToolRegistry`,
so the same engine backs all nine business agents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from ..llm.base import (
    LLMProvider,
    Message,
    Role,
    StopReason,
    ToolResult,
)
from ..tools.base import ToolRegistry


@dataclass
class AgentResult:
    output: str
    messages: List[Message]
    iterations: int
    stopped_early: bool = False


# Hook called after each model step, for tracing/observability.
StepObserver = Callable[["AgentStep"], None]


@dataclass
class AgentStep:
    iteration: int
    reasoning: Optional[str]
    text: str
    tool_calls: List[str] = field(default_factory=list)


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        system_prompt: str = "",
        tools: Optional[ToolRegistry] = None,
        max_iterations: int = 10,
        observer: Optional[StepObserver] = None,
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.tools = tools or ToolRegistry()
        self.max_iterations = max_iterations
        self.observer = observer

    def _finalize_after_max_iterations(
        self,
        messages: List[Message],
        tool_specs: Optional[List[dict]],
    ) -> str:
        """Ask the model for a final answer when the tool loop hits its guard.

        Some providers emit useful "I'll inspect..." text in tool-use turns. If
        we return that after max_iterations, users see a half-answer. This extra
        no-tools turn forces a concise synthesis from the observations already
        collected.
        """
        prompt = (
            "工具调用轮数已经达到上限。不要再调用工具，也不要说“让我继续检查”。"
            "请只基于上面已经返回的工具结果，直接给用户一个完整、可执行的最终答复。"
            "如果仍有数据缺口，请明确标注缺口；不要编造未提供的数据。"
        )
        final_messages = list(messages) + [Message(role=Role.USER, content=prompt)]
        try:
            response = self.provider.complete(
                messages=final_messages,
                tools=None,
                system=self.system_prompt or None,
            )
        except Exception:  # noqa: BLE001 - preserve max-iteration fallback
            response = None
        if response and response.text.strip():
            messages.append(Message(role=Role.ASSISTANT, content=response.text,
                                    reasoning=response.reasoning))
            return response.text
        last_tool = next(
            (r.content for m in reversed(messages) for r in m.tool_results
             if r.content),
            "",
        )
        if last_tool:
            return (
                "分析已达到工具调用上限，下面是目前已拿到的关键数据结果。"
                "建议缩小问题范围后继续追问：\n\n" + last_tool[:4000]
            )
        return "分析已达到工具调用上限，但没有拿到足够的工具结果。请缩小问题范围后再试。"

    def run(self, user_input: str, history: Optional[List[Message]] = None) -> AgentResult:
        messages: List[Message] = list(history or [])
        messages.append(Message(role=Role.USER, content=user_input))

        tool_specs = self.tools.specs() or None
        stopped_early = False
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            response = self.provider.complete(
                messages=messages,
                tools=tool_specs,
                system=self.system_prompt or None,
            )

            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=response.text,
                tool_calls=response.tool_calls,
                reasoning=response.reasoning,
            )
            messages.append(assistant_msg)

            if self.observer:
                self.observer(AgentStep(
                    iteration=iteration,
                    reasoning=response.reasoning,
                    text=response.text,
                    tool_calls=[tc.name for tc in response.tool_calls],
                ))

            if not response.wants_tools:
                return AgentResult(
                    output=response.text,
                    messages=messages,
                    iterations=iteration,
                )

            # Execute every requested tool and feed results back in one tool turn.
            results: List[ToolResult] = []
            for call in response.tool_calls:
                results.append(self._execute(call.id, call.name, call.arguments))
            messages.append(Message(role=Role.TOOL, tool_results=results))

        stopped_early = True
        last_text = self._finalize_after_max_iterations(messages, tool_specs)
        return AgentResult(
            output=last_text,
            messages=messages,
            iterations=iteration,
            stopped_early=stopped_early,
        )

    def run_stream(self, user_input: str, history: Optional[List[Message]] = None):
        """流式版 run：逐事件 yield，供 SSE 实时推给前端。事件：
          ("tools", [名字])  —— 本轮要调用的工具（尚未执行）
          ("token", 文本)    —— 最终答案的 token 增量（真流式打字机效果）
          ("final", AgentResult) —— 结束

        provider 若提供 `stream()` 则真流式；否则退回 complete() 一次性给出（mock 等）。
        """
        messages: List[Message] = list(history or [])
        messages.append(Message(role=Role.USER, content=user_input))
        tool_specs = self.tools.specs() or None
        stream_fn = getattr(self.provider, "stream", None)
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            response: Optional[object] = None
            streamed = False   # 本轮是否已经流出过 token（用于工具轮回滚）
            if stream_fn is not None:
                for kind, payload in stream_fn(messages, tool_specs,
                                               self.system_prompt or None):
                    if kind == "delta":
                        if payload:
                            streamed = True
                            yield ("token", payload)
                    elif kind == "done":
                        response = payload
            else:
                response = self.provider.complete(
                    messages=messages, tools=tool_specs,
                    system=self.system_prompt or None)
                if response.text and not response.wants_tools:
                    streamed = True
                    yield ("token", response.text)

            messages.append(Message(
                role=Role.ASSISTANT, content=response.text,
                tool_calls=response.tool_calls, reasoning=response.reasoning))

            if not response.wants_tools:
                yield ("final", AgentResult(output=response.text,
                                            messages=messages, iterations=iteration))
                return

            # 这一轮是要调工具（不是最终答案）。若刚才流出过临时文本（模型在
            # 调工具前说了句开场白），让前端丢弃它，回到"正在调用…"状态，
            # 避免抓取的几十秒里状态被吞、又显得卡。
            if streamed:
                yield ("reset", None)
            yield ("tools", [tc.name for tc in response.tool_calls])
            results: List[ToolResult] = []
            for call in response.tool_calls:
                results.append(self._execute(call.id, call.name, call.arguments))
            messages.append(Message(role=Role.TOOL, tool_results=results))

        last_text = self._finalize_after_max_iterations(messages, tool_specs)
        if last_text:
            yield ("token", last_text)
        yield ("final", AgentResult(output=last_text, messages=messages,
                                    iterations=iteration, stopped_early=True))

    def _execute(self, call_id: str, name: str, arguments) -> ToolResult:
        tool = self.tools.get(name)
        if tool is None:
            return ToolResult(
                tool_call_id=call_id,
                name=name,
                content=f"error: unknown tool '{name}'",
                is_error=True,
            )
        try:
            output = tool.run(arguments)
            return ToolResult(tool_call_id=call_id, name=name, content=output)
        except Exception as exc:  # surface tool errors to the model, don't crash
            return ToolResult(
                tool_call_id=call_id,
                name=name,
                content=f"error: {type(exc).__name__}: {exc}",
                is_error=True,
            )
