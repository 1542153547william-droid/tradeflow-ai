"""一键运行 #3 图文视频提示词智能体（复用 0.1 模板）。

    python -m examples.run_imagery

默认 MockProvider（无需 key）。切真实模型：设 TRADEFLOW_PROVIDER=bailian 再跑。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradeflow.compose import build_named_agent  # noqa: E402
from tradeflow.tools.imagery import IMAGERY_TOOLS  # noqa: E402


def main() -> None:
    agent = build_named_agent("imagery", tools=IMAGERY_TOOLS)
    print(f"已挂载工具: {[t.name for t in IMAGERY_TOOLS]}\n")

    prompt = (
        "产品：透明防摔手机壳，适配 iPhone 15。给我：1) 主图的中英绘图提示词；"
        "2) 一条 30 秒测评短视频脚本；3) 校验一下这个主图描述是否合规："
        "白底、产品居中、右下角加了促销文字 '50% OFF'。"
    )
    print("=" * 60)
    print(f"USER: {prompt}")
    result = agent.run(prompt)
    print(f"AGENT: {result.output}\n")


if __name__ == "__main__":
    main()
