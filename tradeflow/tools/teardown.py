"""#5 爆款 & 精品拆解智能体的工具集。

拆解本身靠人设 + skills（模型对 get_product_by_asin 抓回的产品数据做分析）；工具负责
两件确定性活：
- `list_hot_asins(category)` —— 从 `data/teardown/爆款ASIN清单.csv` 取某类目的爆款 ASIN。
- `classify_operation_mode(...)` —— 用可解释规则判对手是 精品 / 铺货 / 标品（5.5）。
另复用 #0.5 的 `get_product_by_asin` 抓单个 ASIN 全貌（含评论情感分析）。

阈值先按经验设，后续按老板标准校准（G3）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, List

from ..data_loader import load_data
from .amazon import get_product_by_asin  # 复用 0.5
from .base import tool


@lru_cache(maxsize=None)
def _hot_list() -> tuple:
    return tuple(load_data("teardown", "爆款ASIN清单.csv",
                           required_columns=["类目", "ASIN"]))


@tool
def list_hot_asins(category: str = "", top_n: int = 10) -> Dict[str, object]:
    """列出某类目的爆款 ASIN（供拆解取样）。category 空则返回全部。"""
    low = category.lower().strip()
    rows = [r for r in _hot_list()
            if not low or low in r.get("类目", "").lower()
            or r.get("类目", "").lower() in low]
    return {"category": category,
            "asins": [{"asin": r.get("ASIN", ""), "类目": r.get("类目", ""),
                       "备注": r.get("备注", "")} for r in rows[:top_n]]}


@tool
def classify_operation_mode(review_count: int = 0, image_count: int = 0,
                            has_video: bool = False, variant_count: int = 1,
                            rating: float = 0.0) -> Dict[str, object]:
    """按可解释规则判断竞品运营模式：精品 / 铺货 / 标品（5.5）。

    传入从产品数据里读到的信号（评论数/图片数/是否有视频/变体数/评分）。
    返回 {mode, 精品分, 铺货分, reasons}。阈值后续按老板标准校准（G3）。"""
    reasons: List[str] = []
    refined = 0
    if image_count >= 6:
        refined += 1; reasons.append(f"图片数{image_count}≥6（内容投入高）")
    if has_video:
        refined += 1; reasons.append("有视频（内容投入高）")
    if review_count >= 500:
        refined += 1; reasons.append(f"评论数{review_count}≥500（沉淀深）")
    if rating >= 4.3:
        refined += 1; reasons.append(f"评分{rating}≥4.3（口碑好）")

    volume = 0
    if variant_count >= 6:
        volume += 1; reasons.append(f"变体数{variant_count}≥6（SKU 铺得多）")
    if review_count < 100:
        volume += 1; reasons.append(f"评论数{review_count}<100（单链接沉淀浅）")
    if image_count <= 4:
        volume += 1; reasons.append(f"图片数{image_count}≤4（内容单薄）")
    if not has_video:
        volume += 1; reasons.append("无视频（内容单薄）")

    if refined >= 3:
        mode = "精品"
    elif volume >= 3:
        mode = "铺货"
    else:
        mode = "标品"
    return {"mode": mode, "精品分": refined, "铺货分": volume, "reasons": reasons}


TEARDOWN_TOOLS = [list_hot_asins, get_product_by_asin, classify_operation_mode]
