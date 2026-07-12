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
        wb = load_workbook(io.BytesIO(content), data_only=True, read_only=True)
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


def ads_overview(user_id: str, store_id: str) -> dict[str, Any]:
    with connect() as db:
        rows = db.execute(
            "SELECT r.row_json FROM imported_rows r JOIN import_batches b ON b.id=r.batch_id WHERE r.user_id=? AND r.store_id=? AND b.report_type='ads_search_terms'",
            (user_id, store_id),
        ).fetchall()
    data = [json.loads(r[0]) for r in rows]
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
