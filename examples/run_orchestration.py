"""演示 0.2 编排：智能体互调（A 调 B）+ 流水线。

    python -m examples.run_orchestration

两种编排：
1. 流水线 run_sequence：#2 Listing 写文案 → 把产物喂给 #1 合规复审（确定性链路）。
2. agent_as_tool：把 #1 合规包成工具挂到一个上层智能体上，让它自己决定何时调用
   （#7 选品链就是这个模式：选品调 市场/拆解/合规）。

默认 MockProvider（回显）。切真实模型：设 TRADEFLOW_PROVIDER=bailian 再跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow import registry  # noqa: E402
from tradeflow.compose import build_named_agent  # noqa: E402


def demo_pipeline() -> None:
    print("=" * 60, "\n[1] 流水线：#2 Listing → #1 合规复审")
    trace = registry.run_sequence(
        [("listing", "给美国站写一套新品文案（手机壳，防摔透明）："),
         ("compliance", "对以下文案做合规复审，逐条指出违规并给替代：")],
        initial="产品：TPU 透明防摔手机壳，适配 iPhone 15，加高边框。",
    )
    for step in trace:
        print(f"\n-- {step['agent']} --\n{step['output'][:400]}")


def demo_agent_as_tool() -> None:
    print("\n" + "=" * 60, "\n[2] A 调 B：上层智能体把 #1 合规当工具")
    supervisor = build_named_agent(
        "listing", tools=[registry.agent_as_tool("compliance")])
    print("已挂子智能体工具:", [t.name for t in [registry.agent_as_tool("compliance")]])
    r = supervisor.run("先帮我判断标题 'the best cheapest case' 是否合规，再给建议。")
    print(r.output[:400])


def main() -> None:
    demo_pipeline()
    demo_agent_as_tool()


if __name__ == "__main__":
    main()
