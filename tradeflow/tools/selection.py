"""#7 AI 智能选品智能体的工具集（选品链的"大脑"）。

- `calc_gross_margin(category, sale_price)` —— 接成本测算表算真实毛利（7.4）。
- `score_product(...)` —— 多维加权评分 + 硬性门槛淘汰（7.1/7.5）。

编排（调 #1 合规 / #5 拆解 / #6 市场）由注册表在 build 时把它们当工具挂上（见
registry 的 subagents），本模块不直接依赖它们，避免循环导入。

成本表、权重、门槛均为**占位值**，放 `data/selection/`，替换为老板真实数据即可，
不改代码（阈值/权重校准见 G3）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict

from ..data_loader import load_data
from .base import tool

# 亚马逊类目佣金近似（占位；不同类目不同，后续可细化到成本表）。
_REFERRAL_RATE = 0.15

# 评分维度：全部“越高越好”，0–100。
_DIMS = ("市场容量", "竞争宽松度", "毛利", "侵权安全", "改良空间")


@lru_cache(maxsize=None)
def _cost_table() -> tuple:
    return tuple(load_data("selection", "成本测算表.csv", required_columns=["类目"]))


@lru_cache(maxsize=None)
def _weight_map() -> Dict[str, float]:
    rows = load_data("selection", "评分权重.csv", required_columns=["维度", "权重"])
    out: Dict[str, float] = {}
    for r in rows:
        try:
            out[r["维度"].strip()] = float(r["权重"])
        except (ValueError, KeyError):
            continue
    return out


@lru_cache(maxsize=None)
def _threshold_map() -> Dict[str, str]:
    rows = load_data("selection", "选品门槛.csv", required_columns=["项", "值"])
    return {r["项"].strip(): r.get("值", "").strip() for r in rows if r.get("项")}


def _find_cost(category: str) -> Dict[str, str] | None:
    low = category.lower().strip()
    for r in _cost_table():
        cat = (r.get("类目", "") or "").strip().lower()
        if cat and (cat in low or low in cat):
            return r
    return None


@tool
def calc_gross_margin(category: str, sale_price: float) -> Dict[str, Any]:
    """按成本测算表算某类目在给定售价下的真实毛利（含采购/头程/FBA/包装/佣金/损耗）。

    返回 {found, sale_price, total_cost, profit, margin_pct, breakdown}。"""
    row = _find_cost(category)
    if row is None:
        return {"found": False, "category": category, "note": "成本表未收录该类目"}

    def f(k: str) -> float:
        try:
            return float(row.get(k) or 0)
        except ValueError:
            return 0.0

    fixed = f("采购成本") + f("头程运费") + f("FBA费用") + f("包装")
    referral = round(sale_price * _REFERRAL_RATE, 2)
    loss = round(sale_price * f("损耗率"), 2)
    total = round(fixed + referral + loss, 2)
    profit = round(sale_price - total, 2)
    margin = round(profit / sale_price, 4) if sale_price else 0.0
    return {
        "found": True, "category": category, "sale_price": sale_price,
        "total_cost": total, "profit": profit, "margin_pct": margin,
        "breakdown": {"固定成本(采购+头程+FBA+包装)": round(fixed, 2),
                      "佣金": referral, "损耗": loss},
    }


@tool
def score_product(market_capacity: float, competition_ease: float,
                  gross_margin: float, ip_safety: float,
                  improvement_room: float, category: str = "") -> Dict[str, Any]:
    """多维加权评分 + 硬性门槛淘汰（各维 0–100，均越高越好）。

    维度：市场容量 / 竞争宽松度 / 毛利 / 侵权安全 / 改良空间。权重与门槛读
    data/selection/。返回 {total_score, per_dimension, weights, passed, vetoed_by, verdict}。
    毛利分或侵权安全分低于门槛、或命中禁做品类 → 直接淘汰。"""
    dims = {
        "市场容量": market_capacity, "竞争宽松度": competition_ease,
        "毛利": gross_margin, "侵权安全": ip_safety, "改良空间": improvement_room,
    }
    w = _weight_map()
    wsum = sum(w.get(k, 0) for k in _DIMS) or 1
    total = round(sum(dims[k] * w.get(k, 0) for k in _DIMS) / wsum, 1)

    th = _threshold_map()

    def _num(key: str, default: float) -> float:
        try:
            return float(th.get(key, default))
        except ValueError:
            return default

    vetoed = []
    if gross_margin < _num("最低毛利分", 0):
        vetoed.append(f"毛利分 {gross_margin} < 门槛 {_num('最低毛利分', 0):.0f}")
    if ip_safety < _num("最低侵权安全分", 0):
        vetoed.append(f"侵权安全 {ip_safety} < 门槛 {_num('最低侵权安全分', 0):.0f}")
    banned = [b.strip() for b in th.get("禁做品类", "").split(";") if b.strip()]
    if category and any(b in category or category in b for b in banned):
        vetoed.append(f"命中禁做品类（{category}）")

    passed = not vetoed
    verdict = "淘汰" if vetoed else ("推荐" if total >= 70 else "观望")
    return {"total_score": total, "per_dimension": dims, "weights": w,
            "passed": passed, "vetoed_by": vetoed, "verdict": verdict}


SELECTION_TOOLS = [calc_gross_margin, score_product]
