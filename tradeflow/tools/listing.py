"""#2 Listing 文案生成智能体的工具集。

文案本身由模型按人设 + skills 写；工具负责两件模型做不好的确定性活：
- `inject_keywords(text, category)` —— 从 `data/listing/关键词词根库.csv` 取该类目
  的关键词根，并对给定文案做**覆盖率检查**（已覆盖 / 缺失），支撑"核心关键词覆盖到位"。
- 复用 #1 的 `compliance_gate` —— 生成后过合规（2.8），不重写合规逻辑。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List

from ..data_loader import load_data
from .base import tool
from .compliance import compliance_gate  # 复用 #1，不重写


@lru_cache(maxsize=None)
def _keyword_lib() -> tuple:
    return tuple(load_data("listing", "关键词词根库.csv",
                           required_columns=["词根", "类目"]))


def _roots_for_category(category: str) -> List[Dict[str, str]]:
    """取某类目的词根，按搜索量降序；类目空则返回全部。"""
    low = category.lower().strip()
    rows = [r for r in _keyword_lib()
            if not low or low in (r.get("类目", "").lower())
            or (r.get("类目", "").lower() in low)]
    def _vol(r):
        try:
            return int(r.get("搜索量") or 0)
        except ValueError:
            return 0
    return sorted(rows, key=_vol, reverse=True)


@tool
def inject_keywords(text: str = "", category: str = "",
                    top_n: int = 10) -> Dict[str, object]:
    """给出该类目应埋的核心关键词根，并检查文案对它们的覆盖情况。

    text：已写好的文案（可空，只取词时）。category：产品类目（如 '手机壳'）。
    返回 {candidates:[词根…], covered:[已在文案里的], missing:[还没埋的]}，
    供文案智能体决定把哪些 missing 词根合理埋进标题/五点。"""
    roots = _roots_for_category(category)[:top_n]
    candidates = [r.get("词根", "") for r in roots if r.get("词根")]
    lowered = text.lower()
    covered = [k for k in candidates if k.lower() in lowered]
    missing = [k for k in candidates if k.lower() not in lowered]
    return {"category": category, "candidates": candidates,
            "covered": covered, "missing": missing}


# Listing 智能体挂载的工具：取词/查覆盖 + 复用合规守门员。
LISTING_TOOLS = [inject_keywords, compliance_gate]
