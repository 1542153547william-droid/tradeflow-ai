"""一键运行 #5 爆款拆解智能体（复用 0.1 模板 + 0.5 产品接口）。

    python -m examples.run_teardown

需要 query-system 在跑（默认 http://127.0.0.1:8000，mock 模式即可）。
默认 MockProvider（回显）。切真实模型：设 TRADEFLOW_PROVIDER=bailian 再跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.compose import build_named_agent  # noqa: E402
from tradeflow.tools.teardown import TEARDOWN_TOOLS  # noqa: E402


def main() -> None:
    agent = build_named_agent("teardown", tools=TEARDOWN_TOOLS)
    print(f"已挂载工具: {[t.name for t in TEARDOWN_TOOLS]}\n")

    prompt = ("拆解竞品 ASIN B0HOT0CASE1：抓它的 Listing/变体/定价/痛点，"
              "判断运营模式，最后给结构化 JSON。")
    print("=" * 60)
    print(f"USER: {prompt}")
    result = agent.run(prompt)
    print(f"AGENT: {result.output}\n")


if __name__ == "__main__":
    main()
