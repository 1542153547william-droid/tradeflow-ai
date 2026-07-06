"""每日价格/排名快照存储（按平台 + 商品 + 日期）。

历史价格无法凭单次抓取回溯，只能从接入之日起每天记一笔、往后累积。
按 (platform, product_id, 日期) 每天最多一条（当天多次抓取覆盖为最新值）。
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import List, Optional

from ..models import PricePoint

_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_snapshot (
    platform    TEXT NOT NULL,
    product_id  TEXT NOT NULL,
    snap_date   TEXT NOT NULL,
    price       REAL,
    currency    TEXT,
    rank        INTEGER,
    PRIMARY KEY (platform, product_id, snap_date)
);
"""


class SnapshotStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.execute(_SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def record(self, platform: str, product_id: str, price: Optional[float],
               currency: str, rank: Optional[int]) -> None:
        today = date.today().isoformat()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO price_snapshot "
                "(platform, product_id, snap_date, price, currency, rank) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (platform, product_id, today, price, currency, rank),
            )

    def history(self, platform: str, product_id: str, limit: int = 90) -> List[PricePoint]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT snap_date, price, currency, rank FROM price_snapshot "
                "WHERE platform = ? AND product_id = ? ORDER BY snap_date DESC LIMIT ?",
                (platform, product_id, limit),
            ).fetchall()
        return [
            PricePoint(date=d, price=p, currency=cur or "USD", rank=rk)
            for d, p, cur, rk in reversed(rows)
        ]
