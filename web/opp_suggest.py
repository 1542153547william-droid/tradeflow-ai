"""对话选品的结构化输出（B0）：模型按 JSON 契约给出机会商品清单。

沿用 listing_gen 的稳健模式（一次性 completion + 抠 JSON + 兜底）。当前是模型研判
+ 类目/关键词，未接实时竞品爬虫（那是更重的异步任务，后续增强）；每条附
flag_category_risk 的确定性类目风险，供前端渲染可「放入机会上新」的卡片。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from tradeflow.factory import build_provider
from tradeflow.llm.base import Message, Role
from tradeflow.tools.compliance import flag_category_risk
from tradeflow.tools.amazon import search_products
from web.contracts import OpportunityListContract

_SYS = (
    "你是资深亚马逊选品专家。根据用户给的类目 / 关键词 / 需求，给出值得做的机会商品清单。"
    "只输出一个 JSON 数组，不要任何解释或 markdown 代码块围栏。每个元素结构："
    '{"name": 英文商品名, "cat": 中文类目, "score": 数字(0-10，一位小数), '
    '"margin": 毛利百分比字符串(如 "42%"), "demand": "高|中高|中|低", '
    '"comp": "低|中等|较高|高", "reason": 一句中文推荐理由}。'
    "给 3-5 个，按 score 从高到低排序。"
)


def _extract_json_array(text: str) -> List[Any]:
    """从模型回复里稳健地抠出 JSON 数组：优先 ``` 围栏，否则取首个 [ 到末个 ]。"""
    if not text:
        return []
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        i, j = text.find("["), text.rfind("]")
        raw = text[i:j + 1] if i != -1 and j > i else ""
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def suggest_opportunities(query: str, top_n: int = 4) -> Dict[str, Any]:
    market = search_products.func(query, "amazon", min(max(top_n * 2, 3), 20), "amazon.com", False)
    if market.get("error"):
        return {"query": query, "items": [], "model_ok": False,
                "data_source": "unavailable", "error": market["error"]}
    products = market.get("products") or []
    if not products:
        return {"query": query, "items": [], "model_ok": False,
                "data_source": "unavailable", "error": "真实竞品查询未返回商品，无法生成可信建议"}
    evidence = json.dumps(products, ensure_ascii=False, default=str)[:14000]
    prompt = (f"用户需求：{query}\n请基于以下真实 Amazon 查询结果给出 {top_n} 个机会商品。"
              "不得生成查询结果之外的市场数字；margin 无成本数据时写‘数据不足’。"
              f"\n真实竞品数据：{evidence}")
    text = ""
    try:
        text = build_provider().complete(
            messages=[Message(role=Role.USER, content=prompt)],
            tools=None, system=_SYS).text
    except Exception:  # noqa: BLE001 —— 模型失败也别把接口打崩
        text = ""
    arr = _extract_json_array(text)
    try:
        validated = OpportunityListContract.model_validate({"items": arr})
        arr = [x.model_dump() for x in validated.items]
    except Exception:
        validated = None
        arr = []

    items: List[Dict[str, Any]] = []
    for o in arr[:top_n]:
        if not isinstance(o, dict):
            continue
        name = str(o.get("name") or "").strip()
        if not name:
            continue
        cat = str(o.get("cat") or "").strip()
        risk = flag_category_risk.func(cat or name)
        items.append({
            "name": name, "cat": cat,
            "score": o.get("score"),
            "margin": o.get("margin"),
            "demand": o.get("demand"),
            "comp": o.get("comp"),
            "reason": str(o.get("reason") or "").strip(),
            "risk_level": risk.get("risk_level"),
        })
    return {"query": query, "items": items, "model_ok": bool(validated),
            "data_source": market.get("source", "amazon"),
            "evidence_count": len(products), "fetched_at": market.get("fetched_at")}
