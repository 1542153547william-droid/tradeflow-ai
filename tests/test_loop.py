"""Loop / harness tests. Run: python -m pytest  (or python -m unittest)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.agent.loop import Agent  # noqa: E402
from tradeflow.llm.base import LLMResponse, StopReason, ToolCall  # noqa: E402
from tradeflow.llm.mock_provider import MockProvider  # noqa: E402
from tradeflow.tools.base import ToolRegistry, tool  # noqa: E402


@tool
def calculator(expression: str) -> str:
    """Evaluate arithmetic."""
    return str(eval(expression, {"__builtins__": {}}))  # test-only


class TestToolSchema(unittest.TestCase):
    def test_schema_derivation(self):
        self.assertEqual(calculator.name, "calculator")
        schema = calculator.parameters
        self.assertEqual(schema["properties"]["expression"]["type"], "string")
        self.assertEqual(schema["required"], ["expression"])


class TestAgentLoop(unittest.TestCase):
    def test_single_turn_no_tools(self):
        provider = MockProvider(script=[
            LLMResponse(text="hello", stop_reason=StopReason.END),
        ])
        agent = Agent(provider=provider)
        result = agent.run("hi")
        self.assertEqual(result.output, "hello")
        self.assertEqual(result.iterations, 1)

    def test_tool_call_then_answer(self):
        provider = MockProvider(script=[
            LLMResponse(
                stop_reason=StopReason.TOOL_USE,
                tool_calls=[ToolCall(id="c1", name="calculator",
                                     arguments={"expression": "2+2"})],
            ),
            LLMResponse(text="It is 4.", stop_reason=StopReason.END),
        ])
        agent = Agent(provider=provider, tools=ToolRegistry([calculator]))
        result = agent.run("2+2?")
        self.assertEqual(result.output, "It is 4.")
        self.assertEqual(result.iterations, 2)
        tool_msgs = [m for m in result.messages if m.tool_results]
        self.assertEqual(tool_msgs[0].tool_results[0].content, "4")

    def test_unknown_tool_is_reported_not_crashed(self):
        provider = MockProvider(script=[
            LLMResponse(
                stop_reason=StopReason.TOOL_USE,
                tool_calls=[ToolCall(id="c1", name="nope", arguments={})],
            ),
            LLMResponse(text="done", stop_reason=StopReason.END),
        ])
        agent = Agent(provider=provider, tools=ToolRegistry([calculator]))
        result = agent.run("go")
        err = [m for m in result.messages if m.tool_results][0].tool_results[0]
        self.assertTrue(err.is_error)
        self.assertIn("unknown tool", err.content)

    def test_max_iterations_guard(self):
        # Always asks for a tool -> loop must bail at max_iterations.
        loopy = LLMResponse(
            stop_reason=StopReason.TOOL_USE,
            tool_calls=[ToolCall(id="c", name="calculator",
                                 arguments={"expression": "1+1"})],
        )
        provider = MockProvider(script=[loopy])
        agent = Agent(provider=provider, tools=ToolRegistry([calculator]),
                      max_iterations=3)
        result = agent.run("loop forever")
        self.assertTrue(result.stopped_early)
        self.assertEqual(result.iterations, 3)

    def test_max_iterations_gets_final_synthesis(self):
        loopy = LLMResponse(
            text="Let me check one more thing.",
            stop_reason=StopReason.TOOL_USE,
            tool_calls=[ToolCall(id="c", name="calculator",
                                 arguments={"expression": "1+1"})],
        )
        provider = MockProvider(script=[
            loopy,
            LLMResponse(text="Final answer from tool results.", stop_reason=StopReason.END),
        ])
        agent = Agent(provider=provider, tools=ToolRegistry([calculator]),
                      max_iterations=1)
        result = agent.run("loop once")
        self.assertTrue(result.stopped_early)
        self.assertEqual(result.output, "Final answer from tool results.")

    def test_heuristic_end_to_end(self):
        agent = Agent(provider=MockProvider(), tools=ToolRegistry([calculator]))
        result = agent.run("please compute 6*7")
        self.assertIn("42", result.output)


if __name__ == "__main__":
    unittest.main()
