"""Cookie-session login: password hashing, session tokens, and the
FastAPI dependency that resolves the current user from the request cookie.

No self-serve signup — accounts are created by `web/manage.py`.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request

from config.settings import settings
from web.database import connect


MAX_PASSWORD_BYTES = 72  # bcrypt hard limit; hashpw/checkpw raise ValueError past this.

# 用于登录时给"用户名不存在"这条路径也跑一次 bcrypt 比对，让响应耗时和"用户名存在但密码错"
# 接近，避免用响应时间枚举出哪些用户名已注册。这个 hash 不对应任何真实密码。
DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"tradeflow-dummy-password-for-timing", bcrypt.gensalt()).decode("utf-8")


def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"密码过长（UTF-8 编码后需 ≤{MAX_PASSWORD_BYTES} 字节）")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except ValueError:
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session_in(db: sqlite3.Connection, user_id: str) -> str:
    """跟 create_session 一样，但复用调用方已经打开的连接/事务——登录时要把
    "读密码哈希 → bcrypt 校验 → 写 session" 这几步锁在同一个事务里，不然管理员
    重置密码的窗口期可能夹在校验通过和写 session 之间，旧密码还能拿到有效 session
    （reset_password 那次 DELETE 已经跑完了，赶不上后写入的这一条）。"""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.session_ttl_days)
    db.execute(
        "INSERT INTO sessions(token_hash, user_id, expires_at) VALUES(?,?,?)",
        (_hash_token(token), user_id, expires_at.isoformat()),
    )
    return token


def create_session(user_id: str) -> str:
    with connect() as db:
        return create_session_in(db, user_id)


def resolve_session(token: str) -> Optional[str]:
    if not token:
        return None
    with connect() as db:
        row = db.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash=?",
            (_hash_token(token),),
        ).fetchone()
    if not row:
        return None
    expires_at = datetime.fromisoformat(row["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None
    return row["user_id"]


def delete_session(token: str) -> None:
    if not token:
        return
    with connect() as db:
        db.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))


def current_user(request: Request) -> str:
    token = request.cookies.get(settings.session_cookie_name, "")
    user_id = resolve_session(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return user_id
