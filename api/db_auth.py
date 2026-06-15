"""db_auth.py — auth 表專屬 DB 連線（role: stock_auth）。

與 app.py 的股票唯讀連線(stock_readonly)分離：所有帳號/訂閱讀寫只走這條，
auth 表也只授權給 stock_auth（見 db/init/25_auth.sql），達成 PII 最小權限。
"""
from __future__ import annotations

import os

import psycopg2
import psycopg2.extras

# 未設則 auth 功能停用（回 503），不影響既有唯讀儀表板
AUTH_DATABASE_URL = os.environ.get("AUTH_DATABASE_URL")


def auth_enabled() -> bool:
    return bool(AUTH_DATABASE_URL)


def get_auth_conn():
    if not AUTH_DATABASE_URL:
        raise RuntimeError("AUTH_DATABASE_URL 未設定（auth 功能未啟用）")
    return psycopg2.connect(AUTH_DATABASE_URL)


def auth_query(sql: str, params=None) -> list[dict]:
    """讀（autocommit 由 with 區塊隱式 commit/rollback）。回 list[dict]。"""
    with get_auth_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            if cur.description is None:
                return []
            return [dict(r) for r in cur.fetchall()]


def auth_execute(sql: str, params=None) -> list[dict]:
    """寫（INSERT/UPDATE ... 可帶 RETURNING）。commit 後回 RETURNING 列（無則空）。"""
    with get_auth_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            rows = [dict(r) for r in cur.fetchall()] if cur.description is not None else []
        conn.commit()
        return rows
