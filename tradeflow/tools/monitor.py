"""竞品监控智能体的工具集（PRD 4.4 中 #5/#6 未覆盖的"持续盯竞品"）。

最小闭环：抓快照 → 与上次快照对比 → 变动报告。定时触发与消息推送是基础设施活，
放后续分支；当前手动触发（对话里说"看下竞品有什么变化"即可）。

- `list_watchlist()`        —— 监控清单（data/monitor/监控清单.csv，人工维护）。
- `snapshot_competitors()`  —— 逐个 ASIN 调查询系统抓现状，存 data/monitor/快照/。
- `compare_snapshots()`     —— 对比最近两次快照，按监控规则输出变动与预警。

快照是本地产物（gitignore）；对比是纯函数（`_diff`），可离线测试。
预警阈值在 data/monitor/监控规则.csv（G3 改表不改代码）。
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..data_loader import DATA_ROOT, load_data
from .amazon import get_product_by_asin
from .base import tool

SNAP_DIR = DATA_ROOT / "monitor" / "快照"


def _num(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@lru_cache(maxsize=None)
def _rules() -> Dict[str, float]:
    rows = load_data("monitor", "监控规则.csv", default=[])
    out = {}
    for r in rows:
        val = _num(r.get("值"))
        if r.get("参数") and val is not None:
            out[r["参数"]] = val
    return out


def _rule(key: str, fallback: float) -> float:
    return _rules().get(key, fallback)


def _key_fields(product: Dict[str, Any]) -> Dict[str, Any]:
    """从查询系统的通用分层结构里抽监控关心的字段。"""
    base = product.get("base_info") or {}
    pricing = product.get("pricing") or {}
    return {
        "标题": base.get("title"),
        "品牌": base.get("brand"),
        "价格": _num(pricing.get("price")),
        "评分": _num(base.get("rating")),
        "评论数": _num(base.get("review_count")),
        "排名": base.get("rank"),
    }


def _profile(product: Dict[str, Any]) -> Dict[str, Any]:
    """比监控多抽几维（卖点数/图片/视频/变体/差评占比与痛点词），供横向对比。

    情感分析与高频词字段在不同数据源命名可能不同，这里做兜底探测，取不到就留空。"""
    base = product.get("base_info") or {}
    content = product.get("content") or {}
    fields = _key_fields(product)
    sentiment = (product.get("review_sentiment") or product.get("sentiment")
                 or base.get("sentiment") or {})
    neg = _num(sentiment.get("negative") or sentiment.get("负")
               or sentiment.get("neg"))
    pain = (product.get("pain_points") or product.get("负面关键词")
            or sentiment.get("negative_keywords") or content.get("差评关键词") or [])
    fields.update({
        "卖点数": _num(content.get("bullet_count")
                       or len(content.get("bullets") or []) or None),
        "图片数": _num(content.get("image_count")),
        "有视频": bool(content.get("has_video")),
        "变体数": _num(content.get("variant_count")
                       or len(content.get("variants") or []) or None),
        "差评占比": neg,
        "痛点词": list(pain) if isinstance(pain, (list, tuple)) else [pain],
    })
    return fields


def _best(rows: Dict[str, Dict[str, Any]], field: str, *, high_is_good: bool):
    """在各竞品里挑该维度的最优 ASIN（None 值跳过）。返回 (asin, 值) 或 None。"""
    vals = [(a, r[field]) for a, r in rows.items() if isinstance(r.get(field), (int, float))]
    if not vals:
        return None
    return (max if high_is_good else min)(vals, key=lambda x: x[1])


def _build_comparison(profiles: Dict[str, Dict[str, Any]],
                      my_asin: str = "") -> Dict[str, Any]:
    """多竞品横向对比（纯函数，可离线测）。

    profiles: {asin: _profile(...) 的结果}。my_asin 非空则视为"我方"，标出落后维度。
    产出：对比表 + 各维度赢家 + （有我方时）我方短板 + 差异化机会（竞品共性痛点）。"""
    if not profiles:
        return {"error": "没有可对比的竞品数据"}

    winners = {
        "最低价": _best(profiles, "价格", high_is_good=False),
        "最高分": _best(profiles, "评分", high_is_good=True),
        "评论最多": _best(profiles, "评论数", high_is_good=True),
        "卖点最全": _best(profiles, "卖点数", high_is_good=True),
    }
    winners = {k: {"ASIN": v[0], "值": v[1]} for k, v in winners.items() if v}

    # 差异化机会：所有竞品差评痛点词的共性 = 可主打的改良/攻击点。
    from collections import Counter
    pain = Counter()
    for a, r in profiles.items():
        if a == my_asin:
            continue
        for w in r.get("痛点词") or []:
            if w:
                pain[str(w).strip().lower()] += 1
    opportunities = [{"痛点": w, "出现竞品数": n}
                     for w, n in pain.most_common(8)]

    result: Dict[str, Any] = {
        "对比表": profiles,
        "各维度赢家": winners,
        "差异化机会": opportunities,
    }

    if my_asin and my_asin in profiles:
        me = profiles[my_asin]
        gaps: List[str] = []
        for field, high_good, label in [("评分", True, "评分"),
                                        ("评论数", True, "评论数"),
                                        ("卖点数", True, "卖点数")]:
            best = _best(profiles, field, high_is_good=high_good)
            if best and best[0] != my_asin and isinstance(me.get(field), (int, float)):
                gaps.append(f"{label}落后：我方 {me[field]} vs 最优 {best[1]}（{best[0]}）")
        price_best = _best(profiles, "价格", high_is_good=False)
        if (price_best and isinstance(me.get("价格"), (int, float))
                and me["价格"] > price_best[1]):
            gaps.append(f"价格偏高：我方 ${me['价格']} vs 最低 ${price_best[1]}（{price_best[0]}）")
        result["我方"] = my_asin
        result["我方短板"] = gaps or ["各维度均不落后"]
    return result


def _snap_files() -> List[Path]:
    if not SNAP_DIR.is_dir():
        return []
    return sorted(SNAP_DIR.glob("*.json"))


def _diff(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """对比两份快照（{asin: 字段}），输出变动明细 + 触发预警的项。纯函数。"""
    price_th = _rule("价格变动预警%", 5.0) / 100.0
    review_th = _rule("评论新增预警条数", 20)
    changes: List[Dict[str, Any]] = []
    alerts: List[str] = []
    for asin, cur in new.items():
        prev = old.get(asin)
        if prev is None:
            changes.append({"ASIN": asin, "变动": "新加入监控"})
            continue
        detail: Dict[str, Any] = {"ASIN": asin}
        p0, p1 = prev.get("价格"), cur.get("价格")
        if p0 and p1 and p0 != p1:
            pct = (p1 - p0) / p0
            detail["价格"] = f"{p0} → {p1}（{pct:+.1%}）"
            if abs(pct) >= price_th:
                alerts.append(f"{asin} 价格变动 {pct:+.1%}"
                              f"（阈值 ±{price_th:.0%}）：{p0} → {p1}")
        r0, r1 = prev.get("评论数"), cur.get("评论数")
        if r0 is not None and r1 is not None and r1 != r0:
            detail["评论数"] = f"{r0:.0f} → {r1:.0f}（+{r1 - r0:.0f}）"
            if r1 - r0 >= review_th:
                alerts.append(f"{asin} 评论新增 {r1 - r0:.0f} 条"
                              f"（阈值 {review_th:.0f}），对手在冲评/放量")
        s0, s1 = prev.get("评分"), cur.get("评分")
        if s0 is not None and s1 is not None and s1 != s0:
            detail["评分"] = f"{s0} → {s1}"
            if s1 < s0:
                alerts.append(f"{asin} 评分下滑 {s0} → {s1}，可关注其差评痛点")
        if prev.get("排名") != cur.get("排名"):
            detail["排名"] = f"{prev.get('排名')} → {cur.get('排名')}"
        if len(detail) > 1:
            changes.append(detail)
    gone = [a for a in old if a not in new]
    for asin in gone:
        alerts.append(f"{asin} 本次没抓到（可能下架/断货/被限流），值得跟进")
    return {"变动": changes, "预警": alerts, "消失": gone}


@tool
def list_watchlist() -> Dict[str, Any]:
    """监控清单：正在盯的竞品 ASIN（data/monitor/监控清单.csv）。"""
    rows = load_data("monitor", "监控清单.csv", required_columns=["ASIN"])
    return {"数量": len(rows), "清单": rows}


@tool
def snapshot_competitors(asins: str = "") -> Dict[str, Any]:
    """抓一轮竞品快照存盘（价格/评分/评论数/排名），供后续对比。

    asins：逗号分隔的 ASIN，留空则用监控清单全部。抓取走查询系统，可能较慢。"""
    if asins.strip():
        targets = [{"ASIN": a.strip()} for a in asins.split(",") if a.strip()]
    else:
        targets = load_data("monitor", "监控清单.csv", default=[])
    if not targets:
        return {"error": "监控清单为空：请在 data/monitor/监控清单.csv 添加 ASIN"}

    items: Dict[str, Any] = {}
    errors: List[str] = []
    for row in targets:
        asin = row["ASIN"]
        result = get_product_by_asin.func(
            asin, platform=row.get("平台") or "amazon",
            marketplace=row.get("站点") or "")
        if "error" in result:
            errors.append(f"{asin}: {result['error']}")
            continue
        products = result.get("products") or [result]
        if products:
            items[asin] = _key_fields(products[0])

    if not items:
        return {"error": "一个都没抓到", "明细": errors}
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAP_DIR / f"{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps({"抓取时间": datetime.now().isoformat(),
                                "items": items}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return {"快照": str(path), "成功": len(items), "失败": errors,
            "历史快照数": len(_snap_files())}


@tool
def compare_snapshots() -> Dict[str, Any]:
    """对比最近两次快照，输出竞品变动与预警（阈值见 data/monitor/监控规则.csv）。"""
    files = _snap_files()
    if len(files) < 2:
        return {"error": f"快照不足两次（现有 {len(files)} 次），"
                         "先用 snapshot_competitors 多抓一轮再对比"}
    old = json.loads(files[-2].read_text(encoding="utf-8"))
    new = json.loads(files[-1].read_text(encoding="utf-8"))
    report = _diff(old.get("items", {}), new.get("items", {}))
    return {"对比": f"{files[-2].name} → {files[-1].name}",
            "上次抓取": old.get("抓取时间"), "本次抓取": new.get("抓取时间"),
            **report}


@tool
def compare_competitors(asins: str = "", my_asin: str = "") -> Dict[str, Any]:
    """多竞品横向对比：拉各 ASIN 档案，比价格/评分/评论/卖点/差评痛点，找差异化机会。

    asins：逗号分隔的竞品 ASIN，留空用监控清单。my_asin：我方产品 ASIN（可选），
    传了就在对比里标出我方落后的维度。抓取走查询系统，可能较慢。"""
    ids = [a.strip() for a in asins.split(",") if a.strip()] if asins.strip() else \
        [r["ASIN"] for r in load_data("monitor", "监控清单.csv", default=[]) if r.get("ASIN")]
    if my_asin.strip() and my_asin.strip() not in ids:
        ids.append(my_asin.strip())
    if len(ids) < 2:
        return {"error": "至少需要 2 个 ASIN 才能对比（监控清单为空？可直接传 asins）"}

    profiles: Dict[str, Any] = {}
    errors: List[str] = []
    for asin in ids:
        result = get_product_by_asin.func(asin)
        if "error" in result:
            errors.append(f"{asin}: {result['error']}")
            continue
        products = result.get("products") or [result]
        if products:
            profiles[asin] = _profile(products[0])
    if len(profiles) < 2:
        return {"error": "抓到的有效竞品不足 2 个", "明细": errors}

    report = _build_comparison(profiles, my_asin.strip())
    if errors:
        report["抓取失败"] = errors
    return report


def reset_caches() -> None:
    """测试用。"""
    _rules.cache_clear()


MONITOR_TOOLS = [list_watchlist, snapshot_competitors, compare_snapshots,
                 compare_competitors]
