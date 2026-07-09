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


def reset_caches() -> None:
    """测试用。"""
    _rules.cache_clear()


MONITOR_TOOLS = [list_watchlist, snapshot_competitors, compare_snapshots]
