"""一键运行 #7 智能选品智能体（编排 #1/#5/#6 + 评分/毛利）。

    python -m examples.run_selection

需要 query-system 在跑（#5/#6 会用到，mock 模式即可）。
默认 MockProvider（回显）。切真实模型：设 TRADEFLOW_PROVIDER=bailian 再跑，
才能看到它真正调用 ask_market / ask_teardown / ask_compliance 编排打分。

注意：成本表/权重/门槛为占位值（data/selection/），替换为真实数据即可。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow import registry  # noqa: E402


def main() -> None:
    agent = registry.build("selection")
    tools = [t.name for t in agent.tools._tools.values()]  # type: ignore[attr-defined]
    print(f"已挂载工具（含子智能体）: {tools}\n")

    prompt = ("评估候选品：手机壳（类目=手机壳），计划售价 25.99 美元，美国站。"
              "综合市场/竞品/合规/成本给评分卡和风险收益结论，最后给结构化 JSON。")
    print("=" * 60)
    print(f"USER: {prompt}")
    result = agent.run(prompt)
    print(f"AGENT: {result.output}\n")


if __name__ == "__main__":
    main()
