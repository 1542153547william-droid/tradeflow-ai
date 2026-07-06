"""SQLite 结果缓存。

按 (关键词 + 站点 + top_n) 作键存整份 SearchResult(JSON)，TTL 内命中直接返回，
降低对数据源的请求频率与被封风险。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Optional

from ..models import SearchResult

_SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cache (
    cache_key TEXT PRIMARY KEY,
    payload   TEXT NOT NULL,
    stored_at REAL NOT NULL
);
"""


class CacheStore:
    def __init__(self, db_path: str, ttl_hours: int):
        self.db_path = db_path
        self.ttl_seconds = ttl_hours * 3600
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def make_key(platform: str, keyword: str, marketplace: str, top_n: int) -> str:
        return f"{platform}::{marketplace}::{top_n}::{keyword.strip().lower()}"

    def get(self, key: str) -> Optional[SearchResult]:
        with self._conn() as c:
            row = c.execute(
                "SELECT payload, stored_at FROM search_cache WHERE cache_key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        payload, stored_at = row
        if time.time() - stored_at > self.ttl_seconds:
            self.delete(key)
            return None
        result = SearchResult.model_validate_json(payload)
        result.cached = True
        result.source = "cache"
        return result

    def set(self, key: str, result: SearchResult) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO search_cache (cache_key, payload, stored_at) VALUES (?, ?, ?)",
                (key, result.model_dump_json(), time.time()),
            )

    def delete(self, key: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM search_cache WHERE cache_key = ?", (key,))
