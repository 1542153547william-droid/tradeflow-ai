"""Excel/CSV preview, field mapping, and durable import."""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from typing import Any

from web.database import audit, connect

ALIASES = {
    "sku": {"sku", "seller sku", "商家sku", "卖家sku"},
    "asin": {"asin", "商品asin"},
    "campaign": {"campaign name", "广告活动名称", "广告活动"},
    "search_term": {"customer search term", "客户搜索词", "搜索词"},
    "impressions": {"impressions", "展示量", "曝光量"},
    "clicks": {"clicks", "点击量"},
    "spend": {"spend", "花费", "广告花费"},
    "sales": {"7 day total sales", "7天总销售额", "销售额", "product sales"},
    "orders": {"7 day total orders", "7天总订单数(#)", "订单数", "quantity"},
    "price": {"price", "价格", "售价"},
    "stock": {"stock", "库存", "库存数量"},
    "order_id": {"amazon-order-id", "order id", "订单号"},
    "title": {"title", "product title", "商品标题", "标题"},
    "rating": {"rating", "star rating", "评分", "星级"},
    "review_count": {"review count", "reviews", "评论数", "评价数"},
    "brand": {"brand", "品牌"},
}


def _norm(value: Any) -> str:
    return re.sub(r"[\s_\-]+", " ", str(value or "").strip().lower())


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for col in columns:
        n = _norm(col)
        for target, aliases in ALIASES.items():
            if n in {_norm(a) for a in aliases}:
                out[col] = target
                break
    return out


def detect_report_type(mapping: dict[str, str]) -> str:
    fields = set(mapping.values())
    if {"campaign", "search_term", "clicks", "spend"} <= fields:
        return "ads_search_terms"
    if "order_id" in fields or {"sku", "orders", "sales"} <= fields:
        return "orders"
    if {"sku", "stock"} <= fields:
        return "inventory"
    if "asin" in fields:
        return "competitors"
    return "unknown"


def parse_upload(filename: str, content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(text)))
    elif lower.endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        # Amazon exports occasionally declare a broken worksheet dimension
        # (for example A1:A1 although thousands of cells exist). read_only mode
        # trusts that declaration and silently returns one cell, so use full
        # mode here to discover the actual populated range.
        wb = load_workbook(io.BytesIO(content), data_only=True, read_only=False)
        rows = []
        for ws in wb.worksheets:
            sheet_rows = [list(r) for r in ws.iter_rows(values_only=True)]
            if sheet_rows:
                rows.extend(sheet_rows)
        wb.close()
    else:
        raise ValueError("仅支持 .xlsx、.xlsm 和 .csv")
    rows = [r for r in rows if any(v not in (None, "") for v in r)]
    if not rows:
        raise ValueError("文件中没有可读取的数据")
    known = {_norm(a) for aliases in ALIASES.values() for a in aliases}
    scored = []
    for i, row in enumerate(rows[:30]):
        normalized = [_norm(c) for c in row if _norm(c)]
        recognized = sum(c in known for c in normalized)
        # Business-field matches dominate; earlier rows win exact ties.
        scored.append((recognized * 100 + len(normalized), -i, i))
    _, _, header_idx = max(scored)
    columns = [str(v or f"column_{i+1}").strip() for i, v in enumerate(rows[header_idx])]
    data = []
    for row in rows[header_idx + 1:]:
        item = {columns[i]: row[i] for i in range(min(len(columns), len(row))) if row[i] not in (None, "")}
        if item:
            data.append(item)
    return columns, data


def save_import(user_id: str, store_id: str, filename: str, columns: list[str],
                rows: list[dict[str, Any]], mapping: dict[str, str]) -> dict[str, Any]:
    batch_id = f"imp_{uuid.uuid4().hex[:12]}"
    report_type = detect_report_type(mapping)
    normalized = [{mapping.get(k, k): v for k, v in row.items()} for row in rows]
    with connect() as db:
        db.execute(
            "INSERT INTO import_batches(id,user_id,store_id,filename,report_type,status,row_count,columns_json,mapping_json) VALUES(?,?,?,?,?,'completed',?,?,?)",
            (batch_id, user_id, store_id, filename, report_type, len(normalized),
             json.dumps(columns, ensure_ascii=False), json.dumps(mapping, ensure_ascii=False)),
        )
        db.executemany(
            "INSERT INTO imported_rows(batch_id,user_id,store_id,row_json) VALUES(?,?,?,?)",
            [(batch_id, user_id, store_id, json.dumps(r, ensure_ascii=False, default=str)) for r in normalized],
        )
    audit(user_id, store_id, "import.completed", {"batch_id": batch_id, "rows": len(normalized)})
    return {"id": batch_id, "filename": filename, "report_type": report_type,
            "row_count": len(normalized), "status": "completed"}


def list_imports(user_id: str, store_id: str) -> list[dict[str, Any]]:
    with connect() as db:
        rows = db.execute(
            "SELECT id,filename,report_type,status,row_count,created_at FROM import_batches WHERE user_id=? AND store_id=? ORDER BY created_at DESC",
            (user_id, store_id),
        ).fetchall()
    return [dict(r) for r in rows]


def _latest_imported_rows(user_id: str, store_id: str, report_type: str) -> list[dict[str, Any]]:
    with connect() as db:
        batch = db.execute(
            "SELECT id FROM import_batches WHERE user_id=? AND store_id=? AND report_type=? "
            "AND status='completed' AND row_count>0 ORDER BY created_at DESC, id DESC LIMIT 1",
            (user_id, store_id, report_type),
        ).fetchone()
        if not batch:
            return []
        rows = db.execute(
            "SELECT row_json FROM imported_rows WHERE user_id=? AND store_id=? AND batch_id=?",
            (user_id, store_id, batch["id"]),
        ).fetchall()
    return [json.loads(r[0]) for r in rows]


def ads_overview(user_id: str, store_id: str) -> dict[str, Any]:
    data = _latest_imported_rows(user_id, store_id, "ads_search_terms")
    if not data:
        return {"items": [], "error": "请先导入真实广告搜索词报表"}
    campaigns: dict[str, dict[str, Any]] = {}
    for row in data:
        name = str(row.get("campaign") or "未命名广告活动")
        c = campaigns.setdefault(name, {"campaign": name, "impressions": 0.0, "clicks": 0.0,
                                        "spend": 0.0, "sales": 0.0, "orders": 0.0})
        for key in ("impressions", "clicks", "spend", "sales", "orders"):
            try:
                c[key] += float(str(row.get(key, 0)).replace(",", "") or 0)
            except ValueError:
                pass
    items = []
    for c in campaigns.values():
        c["acos"] = round(c["spend"] / c["sales"], 4) if c["sales"] else None
        c["ctr"] = round(c["clicks"] / c["impressions"], 4) if c["impressions"] else 0
        c["conversion_rate"] = round(c["orders"] / c["clicks"], 4) if c["clicks"] else 0
        items.append(c)
    return {"items": sorted(items, key=lambda x: -x["spend"]), "source": "imported_report",
            "row_count": len(data)}


def ads_chat_analysis(user_id: str, store_id: str) -> str | None:
    """Return a concise, actionable ad report analysis for chat.

    The regular agent tools read files from data/ads. Imported user reports live
    in SQLite, so chat needs this bridge to avoid claiming that no report exists.
    """
    data = _latest_imported_rows(user_id, store_id, "ads_search_terms")
    if not data:
        return None

    def num(value: Any) -> float:
        try:
            return float(str(value or 0).replace(",", "").replace("$", "") or 0)
        except ValueError:
            return 0.0

    campaigns: dict[str, dict[str, Any]] = {}
    terms: dict[tuple[str, str], dict[str, Any]] = {}
    for row in data:
        campaign = str(row.get("campaign") or "未命名广告活动")
        term = str(row.get("search_term") or "(空搜索词)").strip() or "(空搜索词)"
        c = campaigns.setdefault(campaign, {"campaign": campaign, "impressions": 0.0, "clicks": 0.0,
                                            "spend": 0.0, "sales": 0.0, "orders": 0.0})
        t = terms.setdefault((campaign, term), {"campaign": campaign, "term": term, "impressions": 0.0,
                                                "clicks": 0.0, "spend": 0.0, "sales": 0.0, "orders": 0.0})
        for key in ("impressions", "clicks", "spend", "sales", "orders"):
            value = num(row.get(key))
            c[key] += value
            t[key] += value

    def enrich(item: dict[str, Any]) -> dict[str, Any]:
        spend, sales, clicks, impressions, orders = (
            item["spend"], item["sales"], item["clicks"], item["impressions"], item["orders"])
        item["acos"] = spend / sales if sales else None
        item["ctr"] = clicks / impressions if impressions else 0.0
        item["cvr"] = orders / clicks if clicks else 0.0
        item["cpc"] = spend / clicks if clicks else 0.0
        return item

    campaign_items = [enrich(dict(v)) for v in campaigns.values()]
    term_items = [enrich(dict(v)) for v in terms.values()]
    high_acos_campaigns = sorted(
        [x for x in campaign_items if x["spend"] >= 10 and (x["acos"] is None or x["acos"] >= 0.4)],
        key=lambda x: x["spend"],
        reverse=True,
    )[:5]
    negatives = sorted(
        [x for x in term_items if x["spend"] >= 5 and x["orders"] == 0],
        key=lambda x: x["spend"],
        reverse=True,
    )[:8]
    reduce_bids = sorted(
        [x for x in term_items if x["spend"] >= 5 and x["sales"] > 0 and x["acos"] and x["acos"] >= 0.4],
        key=lambda x: x["spend"],
        reverse=True,
    )[:6]
    scale_terms = sorted(
        [x for x in term_items if x["orders"] >= 2 and x["acos"] is not None and 0 < x["spend"]
         and x["acos"] <= 0.2],
        key=lambda x: (x["acos"], -x["orders"]),
    )[:8]

    total = enrich({
        "impressions": sum(x["impressions"] for x in campaign_items),
        "clicks": sum(x["clicks"] for x in campaign_items),
        "spend": sum(x["spend"] for x in campaign_items),
        "sales": sum(x["sales"] for x in campaign_items),
        "orders": sum(x["orders"] for x in campaign_items),
    })

    def money(value: float) -> str:
        return f"{value:.2f}"

    def pct(value: float | None) -> str:
        return "无销售" if value is None else f"{value * 100:.1f}%"

    lines = [
        f"已读取你导入的广告搜索词报表，共 {len(data)} 行。按真实入库数据计算：",
        "",
        "整体盘面：",
        f"- 花费 {money(total['spend'])}，销售额 {money(total['sales'])}，订单 {int(total['orders'])}，ACOS {pct(total['acos'])}，转化率 {pct(total['cvr'])}。",
        "",
        "建议否定或重点排查的搜索词：",
    ]
    if negatives:
        for x in negatives:
            lines.append(
                f"- {x['term']}：{x['campaign']}，花费 {money(x['spend'])}，点击 {int(x['clicks'])}，0 单。")
    else:
        lines.append("- 暂无达到阈值的零转化高花费词。")

    lines.extend(["", "建议降价/降预算的广告活动："])
    if high_acos_campaigns:
        for x in high_acos_campaigns:
            lines.append(
                f"- {x['campaign']}：花费 {money(x['spend'])}，销售额 {money(x['sales'])}，订单 {int(x['orders'])}，ACOS {pct(x['acos'])}。")
    else:
        lines.append("- 暂无明显高 ACOS 活动。")

    lines.extend(["", "建议降低竞价的搜索词："])
    if reduce_bids:
        for x in reduce_bids:
            lines.append(
                f"- {x['term']}：{x['campaign']}，花费 {money(x['spend'])}，销售额 {money(x['sales'])}，ACOS {pct(x['acos'])}。")
    else:
        lines.append("- 暂无明显高 ACOS 搜索词。")

    lines.extend(["", "建议加预算/转精准的词："])
    if scale_terms:
        for x in scale_terms:
            lines.append(
                f"- {x['term']}：{x['campaign']}，订单 {int(x['orders'])}，花费 {money(x['spend'])}，销售额 {money(x['sales'])}，ACOS {pct(x['acos'])}。")
    else:
        lines.append("- 目前没有同时满足 2 单以上且 ACOS <= 20% 的放量词。")

    lines.extend([
        "",
        "执行顺序建议：先否定零转化高花费词，再处理高 ACOS 活动，最后把低 ACOS 出单词单独拉到精准广告里放量。",
    ])
    return "\n".join(lines)


def ads_chat_context(user_id: str, store_id: str) -> str | None:
    """Build a compact live data context for the ad agent to reason over."""
    analysis = ads_chat_analysis(user_id, store_id)
    if not analysis:
        return None
    return (
        "以下是系统刚刚从用户已导入的广告搜索词报表中实时聚合出的真实数据摘要。"
        "你必须基于这些数据回答，不要声称没有收到报表，不要使用样例或 Mock 数据。\n\n"
        f"{analysis}\n\n"
        "回答要求：根据用户具体问题选择分析角度；如果用户只笼统要求分析，"
        "请给出最重要的 3-5 条可执行动作，并说明依据、风险和下一步。"
        "金额单位未知，只能沿用数字本身，禁止标 USD、人民币、¥ 或 $。"
        "没有毛利、成本和目标 ACOS 时，禁止计算利润/亏损金额，只能评价花费、销售额和 ACOS。"
        "不要自行把金额翻倍；不要引用上下文里没有提供的规则表参数。"
    )


def competitor_rows(user_id: str, store_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return real competitor rows uploaded by this store, newest first."""
    with connect() as db:
        rows = db.execute(
            "SELECT r.row_json FROM imported_rows r JOIN import_batches b ON b.id=r.batch_id "
            "WHERE r.user_id=? AND r.store_id=? AND b.report_type='competitors' "
            "ORDER BY r.id DESC LIMIT ?",
            (user_id, store_id, limit),
        ).fetchall()
    return [json.loads(r[0]) for r in rows]
