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
    def make_key(platform: str, keyword: str, marketplace: str, top_n: int,
                include_detail: bool = False, include_reviews: bool = False,
                qa_enabled: bool = False, review_sample_size: int = 0,
                kind: str = "search") -> str:
        # include_detail/include_reviews：否则先跑一次不带详情/评论的搜索，再跑一次
        # 要详情/评论的相同关键词搜索，会直接命中前一次的缓存返回不完整数据，且
        # reviews_status 停在 not_fetched，看起来像"没抓"而不是"命中缓存"。
        # qa_enabled/review_sample_size：这两个是进程级配置（不是每请求参数），改了
        # 配置后如果不带进 key，命中旧缓存会在 TTL 到期前一直返回按旧配置抓的结果。
        # kind：search()（关键词搜索）和 get_product()（按 ASIN 查询）分属不同用途，
        # get_product 用 "asin:{id}" 冒充关键词传进来，理论上可能跟用户真实输入的
        # 搜索词撞车；用 kind 显式区分命名空间，从根上排除这种碰撞。
        return (f"{kind}::{platform}::{marketplace}::{top_n}::"
                f"{int(include_detail)}::{int(include_reviews)}::"
                f"{int(qa_enabled)}::{review_sample_size}::{keyword.strip().lower()}")

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
