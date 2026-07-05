"""TradeFlow-AI — an agent harness for cross-border e-commerce (外贸/Amazon) workflows.

Public surface for building agents. See `tradeflow.factory.build_agent` for the
quick path and `examples/run_demo.py` for a runnable end-to-end loop.
"""

from .agent.loop import Agent, AgentResult, AgentStep
from .llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    ModelConfig,
    Role,
    StopReason,
    ToolCall,
    ToolResult,
)
from .tools.base import Tool, ToolRegistry, tool

__all__ = [
    "Agent", "AgentResult", "AgentStep",
    "LLMProvider", "LLMResponse", "Message", "ModelConfig", "Role",
    "StopReason", "ToolCall", "ToolResult",
    "Tool", "ToolRegistry", "tool",
]
