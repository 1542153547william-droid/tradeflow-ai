"""Store-scoped opportunity persistence backed by SQLite."""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

from .database import audit, connect, init_db


def list_opps(user_id: str = "default", store_id: str = "default") -> List[Dict[str, Any]]:
    init_db()
    with connect() as db:
        rows = db.execute(
            "SELECT id,payload,created_at FROM opportunities WHERE user_id=? AND store_id=? ORDER BY created_at DESC",
            (user_id, store_id),
        ).fetchall()
    return [{**json.loads(r["payload"]), "id": r["id"], "created_at": r["created_at"]} for r in rows]


def add_opp(data: Dict[str, Any], user_id: str = "default", store_id: str = "default") -> Dict[str, Any]:
    init_db()
    opp_id = data.get("id") or f"opp_{uuid.uuid4().hex[:8]}"
    payload = {k: v for k, v in data.items() if k not in {"id", "created_at"}}
    with connect() as db:
        if payload.get("key"):
            db.execute(
                "DELETE FROM opportunities WHERE user_id=? AND store_id=? AND item_key=?",
                (user_id, store_id, payload["key"]),
            )
        db.execute(
            "INSERT INTO opportunities(id,user_id,store_id,item_key,payload) VALUES(?,?,?,?,?)",
            (opp_id, user_id, store_id, payload.get("key"), json.dumps(payload, ensure_ascii=False)),
        )
        created = db.execute("SELECT created_at FROM opportunities WHERE id=?", (opp_id,)).fetchone()[0]
    audit(user_id, store_id, "opportunity.created", {"id": opp_id})
    return {**payload, "id": opp_id, "created_at": created}


def delete_opp(opp_id: str, user_id: str = "default", store_id: str = "default") -> bool:
    init_db()
    with connect() as db:
        cur = db.execute(
            "DELETE FROM opportunities WHERE id=? AND user_id=? AND store_id=?",
            (opp_id, user_id, store_id),
        )
    if cur.rowcount:
        audit(user_id, store_id, "opportunity.deleted", {"id": opp_id})
    return bool(cur.rowcount)
