"""竞品监控智能体 —— 一键运行。

用法：
    python -m examples.run_monitor                    # 默认：看监控清单+最近变动
    python -m examples.run_monitor "抓一轮快照"        # 自定义任务

抓取依赖 query-system 服务在运行（QUERY_API_URL）；对比历史快照则不需要。
"""

from __future__ import annotations

import sys

from tradeflow.registry import build

DEFAULT_TASK = "看下监控清单里的竞品最近有什么变动，有没有需要预警的？"


def main() -> None:
    task = " ".join(sys.argv[1:]).strip() or DEFAULT_TASK
    agent = build("monitor")
    result = agent.run(task)
    print(result.output)


if __name__ == "__main__":
    main()
