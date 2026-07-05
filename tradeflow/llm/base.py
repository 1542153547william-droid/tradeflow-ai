"""Model-agnostic LLM interface.

This is the seam the whole harness talks to. Concrete providers (Anthropic,
mock, later others) implement `LLMProvider`. Business code never imports an SDK
directly — it depends only on the dataclasses and the ABC defined here, so we
can swap models / fill in real API params later without touching the agent loop.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """A model's request to invoke a tool."""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """The outcome of executing a ToolCall, fed back to the model."""

    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


@dataclass
class Message:
    """One turn in the conversation.

    `tool_calls` is set on assistant turns that request tools.
    `tool_results` is set on tool turns that carry execution output back.
    `reasoning` optionally holds the model's thinking trace (when exposed).
    """

    role: Role
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    reasoning: Optional[str] = None


class StopReason(str, Enum):
    END = "end"              # model produced a final answer
    TOOL_USE = "tool_use"    # model wants to call one or more tools
    MAX_TOKENS = "max_tokens"
    ERROR = "error"


@dataclass
class LLMResponse:
    """A single model completion."""

    text: str = ""
    reasoning: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)
    stop_reason: StopReason = StopReason.END
    raw: Optional[Any] = None  # provider-native payload, for debugging

    @property
    def wants_tools(self) -> bool:
        return self.stop_reason == StopReason.TOOL_USE and bool(self.tool_calls)


@dataclass
class ModelConfig:
    """Model / sampling parameters. Real values are filled in later; the harness
    only needs the shape today."""

    model: str = "claude-opus-4-8"
    max_tokens: int = 4096
    temperature: float = 1.0
    thinking: bool = False           # request a reasoning trace when supported
    extra: Dict[str, Any] = field(default_factory=dict)


class LLMProvider(abc.ABC):
    """Everything the agent loop needs from a model backend."""

    def __init__(self, config: Optional[ModelConfig] = None) -> None:
        self.config = config or ModelConfig()

    @abc.abstractmethod
    def complete(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
        system: Optional[str] = None,
    ) -> LLMResponse:
        """Produce one completion given the conversation so far.

        `tools` is a list of JSON-schema tool specs (see tools.base.Tool.spec).
        Providers translate `messages`/`tools` into their native wire format and
        translate the response back into an `LLMResponse`.
        """
        raise NotImplementedError

    @property
    def name(self) -> str:
        return self.__class__.__name__
