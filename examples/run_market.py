"""一键运行 #6 市场分析智能体（复用 0.1 模板 + query-system + #1 风险）。

    python -m examples.run_market

需要 query-system 在跑（默认 http://127.0.0.1:8000，mock 模式即可）。
默认 MockProvider（回显）。切真实模型：设 TRADEFLOW_PROVIDER=bailian 再跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.compose import build_named_agent  # noqa: E402
from tradeflow.tools.market import MARKET_TOOLS  # noqa: E402


def main() -> None:
    agent = build_named_agent("market", tools=MARKET_TOOLS)
    print(f"已挂载工具: {[t.name for t in MARKET_TOOLS]}\n")

    prompt = ("研判关键词 'phone case'（类目=手机壳）是蓝海还是红海："
              "看搜索体量、竞争强度、价格带、类目风险，最后给结构化 JSON。")
    print("=" * 60)
    print(f"USER: {prompt}")
    result = agent.run(prompt)
    print(f"AGENT: {result.output}\n")


if __name__ == "__main__":
    main()
