"""一键运行 #1 合规风控智能体（任务 0.1 的样板 run_<名>.py）。

    python -m examples.run_compliance

默认 MockProvider（无需 key）：主要演示"人设 + skills + 合规工具"如何组合成一个
可运行智能体。切真实模型：设 TRADEFLOW_PROVIDER=bailian/anthropic 再跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.compose import build_named_agent, compose_system_prompt  # noqa: E402
from tradeflow.tools.compliance import COMPLIANCE_TOOLS  # noqa: E402


def main() -> None:
    print("=== 组合出的系统提示（前 400 字）===")
    print(compose_system_prompt("compliance")[:400], "...\n")

    agent = build_named_agent("compliance", tools=COMPLIANCE_TOOLS)
    print(f"已挂载工具: {[t.name for t in COMPLIANCE_TOOLS]}\n")

    for prompt in [
        "帮我审这条美国站标题是否合规：the best cheapest AirPods case, 100% cure for scratches",
        "我想做医疗器械类目的选品，帮我看下合规风险。",
    ]:
        print("=" * 60)
        print(f"USER: {prompt}")
        result = agent.run(prompt)
        print(f"AGENT: {result.output}\n")


if __name__ == "__main__":
    main()
