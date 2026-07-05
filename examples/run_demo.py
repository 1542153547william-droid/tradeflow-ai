"""End-to-end demo of the harness on the MockProvider (no API key needed).

    python -m examples.run_demo

Shows the reason -> tool_call -> observe -> answer loop firing, with a live
trace of each step.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.agent.loop import AgentStep  # noqa: E402
from tradeflow.factory import build_agent  # noqa: E402


def trace(step: AgentStep) -> None:
    print(f"\n── step {step.iteration} ──")
    if step.reasoning:
        print(f"  reasoning: {step.reasoning}")
    if step.tool_calls:
        print(f"  tool_calls: {', '.join(step.tool_calls)}")
    if step.text:
        print(f"  text: {step.text}")


def main() -> None:
    agent = build_agent(observer=trace)  # mock provider by default

    for prompt in [
        "What is 12 * (3 + 4)?",
        "Draft a headline: the best cheapest phone case, no.1 seller.",
    ]:
        print("\n" + "=" * 60)
        print(f"USER: {prompt}")
        result = agent.run(prompt)
        print(f"\nFINAL ({result.iterations} iters, "
              f"early_stop={result.stopped_early}): {result.output}")


if __name__ == "__main__":
    main()
