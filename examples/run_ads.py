"""#4 广告优化分析智能体 —— 一键运行。

用法：
    python -m examples.run_ads                       # 默认诊断任务
    python -m examples.run_ads "帮我看看哪些词在烧钱"  # 自定义问题

数据：data/ads/ 有真实报表（*_真实.*，不入库）用真实的，否则用仓库样例。
"""

from __future__ import annotations

import sys

from tradeflow.registry import build

DEFAULT_TASK = (
    "帮我诊断广告：整体和各活动盘面如何？哪些搜索词在亏钱、哪些值得加价？"
    "给出可执行的调词动作清单，并导出否定词。"
)


def main() -> None:
    task = " ".join(sys.argv[1:]).strip() or DEFAULT_TASK
    agent = build("ads")
    result = agent.run(task)
    print(result.output)


if __name__ == "__main__":
    main()
