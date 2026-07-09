"""机会上新列表的极简持久化（单 JSON 文件 + 锁）。

不是真正的数据库——只是让「机会上新」跨刷新/重启存活，够 demo / 单店铺用。
等 C3 持久化层落地时，换成 SQLite/Postgres，接口保持不变即可。
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

_DIR = Path(__file__).parent / "_store"
_FILE = _DIR / "opportunities.json"
_LOCK = threading.Lock()


def _read() -> List[Dict[str, Any]]:
    if not _FILE.exists():
        return []
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write(items: List[Dict[str, Any]]) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _FILE.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def list_opps() -> List[Dict[str, Any]]:
    with _LOCK:
        return _read()


def add_opp(data: Dict[str, Any]) -> Dict[str, Any]:
    """新增一条机会。带 key 时按 key 去重（同一商品不重复入库），最新的排最前。"""
    with _LOCK:
        items = _read()
        item = {**data,
                "id": data.get("id") or f"opp_{uuid.uuid4().hex[:8]}",
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        if item.get("key"):
            items = [x for x in items if x.get("key") != item["key"]]
        items.insert(0, item)
        _write(items)
        return item


def delete_opp(opp_id: str) -> bool:
    with _LOCK:
        items = _read()
        kept = [x for x in items if x.get("id") != opp_id]
        _write(kept)
        return len(kept) != len(items)
