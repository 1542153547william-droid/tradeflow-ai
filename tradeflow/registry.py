"""智能体注册表 + 编排（任务 0.2）。

- **注册表**：一处登记每个业务智能体（名字/展示名/描述/工具集），供 `build(name)`
  统一构建，也供 web 层列出可选智能体。
- **A 调 B**：`agent_as_tool(name)` 把一个已注册智能体包装成一个 Tool，挂到另一个
  智能体上，后者就能像调工具一样调它（如 #7 选品调 #1 合规 / #5 拆解 / #6 市场）。
- **流水线**：`run_sequence(...)` 按顺序跑多个智能体，把上一个输出喂给下一个（确定性
  编排，适合"选品调 市场→拆解→合规"这类固定链路）。

新增一个智能体：加它的 3 个文件 + 工具后，在 REGISTRY 里登一行即可被编排/被前端选中。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from .agent.loop import Agent
from .compose import build_named_agent
from .tools.base import Tool, tool
from .tools.ads import ADS_TOOLS
from .tools.compliance import COMPLIANCE_TOOLS
from .tools.imagery import IMAGERY_TOOLS
from .tools.listing import LISTING_TOOLS
from .tools.market import MARKET_TOOLS
from .tools.monitor import MONITOR_TOOLS
from .tools.selection import SELECTION_TOOLS
from .tools.teardown import TEARDOWN_TOOLS
from .tools.amazon import AMAZON_TOOLS


@dataclass(frozen=True)
class AgentSpec:
    name: str            # 与 prompts/<name>.md、skills/<name>/ 对应的键
    label: str           # 前端展示名
    description: str     # 一句话说明（也用作 agent_as_tool 的工具描述）
    tools: Tuple[Tool, ...]
    subagents: Tuple[str, ...] = ()   # 编排：把这些已注册智能体当工具挂上（如 #7 调 #1#5#6）


REGISTRY: Dict[str, AgentSpec] = {
    "compliance": AgentSpec(
        "compliance", "#1 合规风控",
        "审文案/类目合规：禁词+IP+类目风险+白名单", tuple(COMPLIANCE_TOOLS)),
    "listing": AgentSpec(
        "listing", "#2 Listing 文案",
        "产出多站点 Listing 文案，自动埋词并过合规", tuple(LISTING_TOOLS + AMAZON_TOOLS)),
    "imagery": AgentSpec(
        "imagery", "#3 图文视频提示词",
        "绘图 prompt + 短视频脚本 + 图片规范校验", tuple(IMAGERY_TOOLS)),
    "ads": AgentSpec(
        "ads", "#4 广告优化",
        "解析广告/结算报表：指标盘面+SKU盈亏线+搜索词三分类+调价否定建议", tuple(ADS_TOOLS)),
    "teardown": AgentSpec(
        "teardown", "#5 爆款拆解",
        "拆竞品 ASIN：Listing/变体/定价/痛点 + 运营模式判定", tuple(TEARDOWN_TOOLS + AMAZON_TOOLS)),
    "market": AgentSpec(
        "market", "#6 市场分析",
        "类目/关键词蓝海红海研判：体量/竞争强度/价格带/风险", tuple(MARKET_TOOLS + AMAZON_TOOLS)),
    "monitor": AgentSpec(
        "monitor", "竞品监控分析",
        "盯竞品：快照对比预警 + 多竞品横向对比找我方短板与差异化机会", tuple(MONITOR_TOOLS)),
    "selection": AgentSpec(
        "selection", "#7 智能选品",
        "选品决策：多维评分+毛利测算，综合 #1/#5/#6 给风险收益结论",
        tuple(SELECTION_TOOLS + AMAZON_TOOLS), subagents=("compliance", "teardown", "market")),
}


def list_specs() -> List[AgentSpec]:
    return list(REGISTRY.values())


def get_spec(name: str) -> AgentSpec:
    if name not in REGISTRY:
        raise KeyError(f"未注册的智能体: {name!r}（已注册: {list(REGISTRY)}）")
    return REGISTRY[name]


def build(name: str, observer=None, **kwargs) -> Agent:
    """按注册信息构建一个智能体（人设+skills+它的工具集+声明的子智能体工具）。"""
    spec = get_spec(name)
    tools = _dedupe_tools(list(spec.tools) + [agent_as_tool(n) for n in spec.subagents])
    return build_named_agent(name, tools=tools, observer=observer, **kwargs)


def _dedupe_tools(tools: List[Tool]) -> List[Tool]:
    """按工具名去重、保留首次出现顺序。

    多个工具集会共享同一工具（如 #5 拆解复用 amazon 的 get_product_by_asin），
    拼接后可能重名；ToolRegistry 对重名会直接报错，这里先去重避免构建失败。
    """
    seen: set = set()
    unique: List[Tool] = []
    for t in tools:
        if t.name in seen:
            continue
        seen.add(t.name)
        unique.append(t)
    return unique


def agent_as_tool(name: str) -> Tool:
    """把一个已注册智能体包装成工具，供别的智能体调用（0.2：A 调 B）。"""
    spec = get_spec(name)

    def _run(task: str) -> str:
        return build(name).run(task).output

    _run.__name__ = f"ask_{name}"
    _run.__doc__ = (f"调用「{spec.label}」子智能体处理一项任务并返回其结论。"
                    f"适用：{spec.description}。task 传要它处理的完整需求文本。")
    return tool(_run)


def run_sequence(steps: Sequence[Tuple[str, str]], initial: str,
                 observer=None) -> List[Dict[str, str]]:
    """按顺序跑一条智能体流水线，把上一步输出拼进下一步输入。

    steps：[(智能体名, 引导语), ...]；引导语放在上游产物前面（可空串）。
    initial：喂给第一个智能体的原始输入。
    返回每步的 {agent, input, output}，末步 output 即最终结果。
    """
    context = initial
    trace: List[Dict[str, str]] = []
    for name, lead in steps:
        prompt = f"{lead}\n\n{context}".strip() if lead else context
        output = build(name, observer=observer).run(prompt).output
        trace.append({"agent": name, "input": prompt, "output": output})
        context = output
    return trace


__all__ = ["AgentSpec", "REGISTRY", "list_specs", "get_spec",
           "build", "agent_as_tool", "run_sequence"]
