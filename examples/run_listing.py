"""一键运行 #2 Listing 文案智能体（复用 0.1 模板 + #1 compliance_gate）。

    python -m examples.run_listing

默认 MockProvider（无需 key）：演示"人设 + 写作规则 + 取词/合规工具"组合成智能体。
切真实模型：设 TRADEFLOW_PROVIDER=bailian/anthropic 再跑，即可看到真正生成的文案。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.compose import build_named_agent  # noqa: E402
from tradeflow.tools.listing import LISTING_TOOLS  # noqa: E402


def main() -> None:
    agent = build_named_agent("listing", tools=LISTING_TOOLS)
    print(f"已挂载工具: {[t.name for t in LISTING_TOOLS]}\n")

    prompt = (
        "给美国站写一套新品文案。产品：手机壳，适配 iPhone 15，"
        "材质 TPU，防摔、透明、带加高边框。品况=新品。"
    )
    print("=" * 60)
    print(f"USER: {prompt}")
    result = agent.run(prompt)
    print(f"AGENT: {result.output}\n")


if __name__ == "__main__":
    main()
