"""结构化 Listing 素材生成（B0）。

用一次性 completion（非工具循环）让 #2 模型按 JSON 契约产出标题/五点/描述，稳健解析；
关键词优先用数据层词根库（inject_keywords）确定性补齐；最后统一过 compliance_gate。
即便模型没吐出规范 JSON，也用兜底文案 + 词根库保证接口始终返回可用结构。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from tradeflow.factory import build_provider
from tradeflow.llm.base import Message, Role
from tradeflow.tools.compliance import compliance_gate
from tradeflow.tools.listing import inject_keywords

_SYS = (
    "你是资深亚马逊 Listing 文案专家。只输出一个 JSON 对象，不要任何解释、前后缀或 markdown 代码块围栏。"
    'JSON 结构：{"title": string, "bullets": string[], "description": string, "keywords": string[]}。'
    "要求：title 为英文、≤200 字符且含核心关键词；bullets 恰好 5 条、每条以【中文亮点】开头；"
    "description 为一段英文 A+ 文案；keywords 为 8-12 个英文搜索词。"
    "严禁使用 best / no.1 / #1 / 100% cure / fda approved / cheapest / guaranteed 等极限词与虚假认证。"
)

_FALLBACK_BULLETS = [
    "【核心卖点】突出该品类第一诉求，覆盖主搜索词",
    "【差异化】对比竞品的改良点，回应差评痛点",
    "【使用场景】明确适用场景与人群",
    "【材质规格】关键参数，降低退货率",
    "【安心保障】质保 / 售后承诺",
]


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型回复里稳健地抠出 JSON 对象：优先 ```json 围栏，否则取首个 { 到末个 }。"""
    if not text:
        return {}
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        i, j = text.find("{"), text.rfind("}")
        raw = text[i:j + 1] if i != -1 and j > i else ""
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def generate_listing(name: str, category: str = "", site: str = "US") -> Dict[str, Any]:
    kw = inject_keywords.func("", category, 12)
    candidates: List[str] = kw.get("candidates", []) or []

    prompt = (f"为商品「{name}」（类目：{category or '未指定'}）撰写亚马逊 {site} 站 Listing 素材。"
              f"可优先埋入这些核心关键词根：{', '.join(candidates) or '（无，请自拟）'}。")
    text = ""
    try:
        text = build_provider().complete(
            messages=[Message(role=Role.USER, content=prompt)],
            tools=None, system=_SYS).text
    except Exception:  # noqa: BLE001 —— 模型失败也要给可用兜底，别把接口打崩
        text = ""
    data = _extract_json(text)

    title = str(data.get("title") or f"{name} - Premium Quality for Everyday Use").strip()

    bullets = data.get("bullets")
    if not isinstance(bullets, list) or not bullets:
        bullets = list(_FALLBACK_BULLETS)
    bullets = [str(b) for b in bullets][:5]

    description = str(data.get("description") or "").strip()

    keywords = data.get("keywords")
    if not isinstance(keywords, list) or not keywords:
        keywords = candidates[:8]
    keywords = [str(k) for k in keywords]

    compliance = compliance_gate.func("\n".join([title, *bullets, description]), category, site)

    return {
        "name": name, "category": category, "site": site,
        "title": title, "bullets": bullets,
        "description": description, "keywords": keywords,
        "candidates": candidates,
        "model_ok": bool(data),          # 模型是否吐出可解析 JSON（否则用了兜底）
        "compliance": compliance,
    }
