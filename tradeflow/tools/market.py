"""#6 市场数据分析智能体的工具集。

- `assess_competition(keyword)` —— 抓一批竞品样本（复用 query-system search_products），
  算出竞争强度指标：头部集中度、评论门槛、价格带分布、品牌数、均分（6.1/6.2/6.3）。
- `parse_keyword_market_data(keyword)` —— 读 `data/market/关键词市场数据.csv` 拿搜索
  体量与淡旺季（6.1/6.4）。真实关键词工具导出到位后替换此表即可。
- 复用 #1 `flag_category_risk` —— 高风险类目标记（6.5）。

蓝海/红海的量化阈值先按经验，后续按老板标准校准（G3）。
"""

from __future__ import annotations

from functools import lru_cache
from statistics import median
from typing import Any, Dict, List

from ..data_loader import load_data
from .amazon import search_products  # 复用查询系统
from .base import tool
from .compliance import flag_category_risk  # 复用 #1


@lru_cache(maxsize=None)
def _market_table() -> tuple:
    return tuple(load_data("market", "关键词市场数据.csv",
                           required_columns=["关键词"]))


def _competition_metrics(products: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从竞品样本算竞争强度指标（纯函数，便于脱网测试）。"""
    if not products:
        return {"sample_size": 0, "note": "无竞品样本"}
    reviews = sorted(
        [int((p.get("base_info") or {}).get("review_count") or 0) for p in products],
        reverse=True)
    prices = [float((p.get("pricing") or {}).get("price"))
              for p in products if (p.get("pricing") or {}).get("price") is not None]
    ratings = [float((p.get("base_info") or {}).get("rating"))
               for p in products if (p.get("base_info") or {}).get("rating") is not None]
    brands = {(p.get("base_info") or {}).get("brand") for p in products
              if (p.get("base_info") or {}).get("brand")}

    total_rev = sum(reviews) or 1
    top3_share = round(sum(reviews[:3]) / total_rev, 3)
    price_block: Dict[str, Any] = {}
    if prices:
        lo, hi = min(prices), max(prices)
        span = (hi - lo) / 3 or 1
        bands = {"low": 0, "mid": 0, "high": 0}
        for pr in prices:
            k = "low" if pr < lo + span else ("mid" if pr < lo + 2 * span else "high")
            bands[k] += 1
        price_block = {"min": round(lo, 2), "median": round(median(prices), 2),
                       "max": round(hi, 2), "bands": bands}

    return {
        "sample_size": len(products),
        "brand_count": len(brands),
        "head_concentration_top3": top3_share,   # 头部前3评论占比：越高越红海
        "review_threshold_median": int(median(reviews)),  # 评论门槛（中位）
        "review_max": reviews[0],
        "avg_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "price": price_block,
    }


@tool
def assess_competition(keyword: str, platform: str = "amazon",
                       top_n: int = 10, marketplace: str = "") -> Dict[str, Any]:
    """抓关键词下的竞品样本并测算竞争强度（头部集中度/评论门槛/价格带/品牌数）。

    返回 {keyword, ...指标}。头部集中度高、评论门槛高、品牌集中 → 偏红海。"""
    result = search_products.func(keyword, platform, top_n, marketplace)
    if isinstance(result, dict) and result.get("error"):
        return {"keyword": keyword, "error": result["error"]}
    metrics = _competition_metrics((result or {}).get("products", []))
    return {"keyword": keyword, **metrics}


@tool
def parse_keyword_market_data(keyword: str) -> Dict[str, Any]:
    """查关键词的搜索体量与淡旺季（读市场数据表）。未命中返回 found=False。"""
    low = keyword.lower().strip()
    for row in _market_table():
        kw = (row.get("关键词", "") or "").strip()
        if kw and (kw.lower() in low or low in kw.lower()):
            return {"found": True, "关键词": kw,
                    "月搜索量": row.get("月搜索量", ""),
                    "竞争度": row.get("竞争度", ""),
                    "旺季": row.get("旺季", "")}
    return {"found": False, "keyword": keyword, "note": "市场数据表未收录该词"}


MARKET_TOOLS = [assess_competition, parse_keyword_market_data, flag_category_risk]
