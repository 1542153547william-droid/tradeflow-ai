"""SQLite persistence for the public MVP.

The schema is deliberately small but every business row is scoped by user and
store so moving to Postgres later does not require changing API contracts.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DB_PATH = Path(os.environ.get("TRADEFLOW_DB_PATH", Path(__file__).parent / "_store" / "tradeflow.db"))


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def init_db() -> None:
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS stores (
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL, name TEXT NOT NULL,
              marketplace TEXT NOT NULL DEFAULT 'US', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS opportunities (
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL, store_id TEXT NOT NULL,
              item_key TEXT, payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(store_id) REFERENCES stores(id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_opp_key
              ON opportunities(user_id, store_id, item_key) WHERE item_key IS NOT NULL;
            CREATE TABLE IF NOT EXISTS import_batches (
              id TEXT PRIMARY KEY, user_id TEXT NOT NULL, store_id TEXT NOT NULL,
              filename TEXT NOT NULL, report_type TEXT NOT NULL, status TEXT NOT NULL,
              row_count INTEGER NOT NULL DEFAULT 0, columns_json TEXT NOT NULL DEFAULT '[]',
              mapping_json TEXT NOT NULL DEFAULT '{}', error TEXT,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(store_id) REFERENCES stores(id)
            );
            CREATE TABLE IF NOT EXISTS imported_rows (
              id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL,
              user_id TEXT NOT NULL, store_id TEXT NOT NULL, row_json TEXT NOT NULL,
              FOREIGN KEY(batch_id) REFERENCES import_batches(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, store_id TEXT,
              action TEXT NOT NULL, detail_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        db.execute("INSERT OR IGNORE INTO users(id,name) VALUES('default','默认用户')")
        db.execute("INSERT OR IGNORE INTO stores(id,user_id,name,marketplace) VALUES('default','default','默认店铺','US')")


def audit(user_id: str, store_id: str | None, action: str, detail: Any = None) -> None:
    with connect() as db:
        db.execute(
            "INSERT INTO audit_log(user_id,store_id,action,detail_json) VALUES(?,?,?,?)",
            (user_id, store_id, action, json.dumps(detail or {}, ensure_ascii=False)),
        )
