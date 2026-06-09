"""
stock-ai FastMCP server
Runs on 0.0.0.0:8000 (container) → host port 7001
Connects to TimescaleDB via DATABASE_URL env var
"""

import os
import re
import json
import logging
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras
from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stock-ai")

DATABASE_URL = os.environ.get("DATABASE_URL", "")

mcp = FastMCP("stock-ai")


# ─── DB helpers ──────────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


def query_rows(sql: str, params=None, limit: int | None = None) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchmany(limit) if limit else cur.fetchall()
            return [dict(r) for r in rows]


def execute_write(sql: str, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


# ─── run_query safety guard ───────────────────────────────────────────────────

# Keywords that must NOT appear anywhere in the statement (after stripping comments)
_FORBIDDEN_PATTERN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|COPY|EXECUTE|CALL|DO)\b",
    re.IGNORECASE,
)

_MAX_ROWS = 200


def _validate_read_only(sql: str) -> str:
    """Validate that sql is a single read-only SELECT/WITH statement.

    Returns the cleaned sql string on success, raises ValueError on failure.
    """
    cleaned = sql.strip()

    # Must start with SELECT or WITH (case-insensitive)
    if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):
        raise ValueError(
            "REJECTED: only SELECT or WITH queries are allowed. "
            f"Statement starts with: {cleaned[:40]!r}"
        )

    # Strip single-line comments before keyword scanning
    no_comments = re.sub(r"--[^\n]*", " ", cleaned)
    # Strip block comments
    no_comments = re.sub(r"/\*.*?\*/", " ", no_comments, flags=re.DOTALL)

    # Reject any forbidden write/DDL keyword
    m = _FORBIDDEN_PATTERN.search(no_comments)
    if m:
        raise ValueError(
            f"REJECTED: forbidden keyword '{m.group()}' detected. "
            "Only read-only queries are permitted."
        )

    # Reject multi-statement (semicolon not at the very end)
    # Allow trailing semicolon but not semicolons inside the statement
    stripped_semi = no_comments.rstrip().rstrip(";").rstrip()
    if ";" in stripped_semi:
        raise ValueError(
            "REJECTED: multiple statements (semicolon) are not allowed."
        )

    return cleaned


# ─── Tools ───────────────────────────────────────────────────────────────────

@mcp.tool()
def list_tables() -> list[str]:
    """List all user tables and views in the public schema."""
    rows = query_rows(
        """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_type, table_name
        """
    )
    return [f"{r['table_name']} ({r['table_type']})" for r in rows]


@mcp.tool()
def describe_table(name: str) -> list[dict]:
    """Describe columns of a table or view by name."""
    rows = query_rows(
        """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (name,),
    )
    if not rows:
        return [{"error": f"Table or view '{name}' not found in public schema."}]
    return rows


@mcp.tool()
def run_query(sql: str) -> dict:
    """Execute a read-only SELECT or WITH query (max 200 rows).

    Security: only SELECT/WITH statements are allowed.
    INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE,
    COPY, EXECUTE, CALL, DO and multi-statement (;) are all rejected.
    """
    try:
        clean_sql = _validate_read_only(sql)
    except ValueError as e:
        return {"status": "error", "message": str(e), "rows": []}

    try:
        rows = query_rows(clean_sql, limit=_MAX_ROWS)
        return {"status": "ok", "count": len(rows), "rows": rows}
    except Exception as e:
        return {"status": "error", "message": str(e), "rows": []}


@mcp.tool()
def get_latest_price(symbol: str) -> dict:
    """Get the latest daily price row for a symbol."""
    rows = query_rows(
        """
        SELECT symbol, ts, open, high, low, close, volume
        FROM daily_prices
        WHERE symbol = %s
          AND ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
        ORDER BY ts DESC
        LIMIT 1
        """,
        (symbol,),
    )
    if not rows:
        return {"error": f"No recent price data found for {symbol}."}
    return rows[0]


@mcp.tool()
def get_indicators(symbol: str, limit: int = 20) -> list[dict]:
    """Get recent price + technical indicators for a symbol from v_price_indicators."""
    rows = query_rows(
        """
        SELECT *
        FROM v_price_indicators
        WHERE symbol = %s
        ORDER BY ts DESC
        LIMIT %s
        """,
        (symbol, limit),
    )
    if not rows:
        return [{"error": f"No indicator data found for {symbol}."}]
    return rows


@mcp.tool()
def get_signals(symbol: str) -> list[dict]:
    """Get recent 5/10/20 MA strategy signals for a symbol from v_strategy_5_10_20."""
    rows = query_rows(
        """
        SELECT *
        FROM v_strategy_5_10_20
        WHERE symbol = %s
          AND ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '30 days'
        ORDER BY ts DESC
        LIMIT 30
        """,
        (symbol,),
    )
    if not rows:
        return [{"error": f"No signal data found for {symbol}."}]
    return rows


@mcp.tool()
def scan_strategy(market: str | None = None, limit: int = 20) -> list[dict]:
    """Scan for top strategy candidates today.

    Uses daily_candidates if it exists, otherwise falls back to v_strategy_latest.
    Filters to buy/watch signals sorted by score descending.
    market: optional filter e.g. 'TW', 'US'
    """
    # Check if daily_candidates exists
    exists_rows = query_rows(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'daily_candidates'
        """
    )

    if exists_rows:
        market_clause = "AND market = %s" if market else ""
        params: tuple = (market, limit) if market else (limit,)
        rows = query_rows(
            f"""
            SELECT *
            FROM daily_candidates
            WHERE signal_type IN ('buy','watch')
              {market_clause}
            ORDER BY score DESC NULLS LAST
            LIMIT %s
            """,
            params,
        )
    else:
        # Fallback: v_strategy_latest, filter to latest date
        market_join = ""
        market_clause = ""
        params = (limit,)
        if market:
            market_join = "JOIN symbols s ON v.symbol = s.symbol"
            market_clause = "AND s.market = %s"
            params = (market, limit)

        rows = query_rows(
            f"""
            SELECT v.*
            FROM v_strategy_latest v
            {market_join}
            WHERE v.signal_type IN ('buy','watch')
              AND v.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
              {market_clause}
            ORDER BY v.score DESC NULLS LAST
            LIMIT %s
            """,
            params,
        )

    if not rows:
        return [{"message": "No buy/watch candidates found for today."}]
    return rows


@mcp.tool()
def get_chips(symbol: str) -> dict:
    """Get latest chip data (institutional + margin) for a symbol."""
    result: dict[str, Any] = {}

    # Check tables exist
    for tbl in ("chip_institutional", "chip_margin"):
        exists = query_rows(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
            (tbl,),
        )
        if not exists:
            result[tbl] = f"Table '{tbl}' does not exist yet."
            continue
        rows = query_rows(
            f"SELECT * FROM {tbl} WHERE symbol=%s ORDER BY ts DESC LIMIT 5",
            (symbol,),
        )
        result[tbl] = rows if rows else f"No chip data for {symbol} in {tbl}."

    return result


@mcp.tool()
def get_strategy(symbol: str) -> dict:
    """Get the latest strategy signal row for a specific symbol from v_strategy_latest."""
    rows = query_rows(
        """
        SELECT *
        FROM v_strategy_latest
        WHERE symbol = %s
          AND ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
        ORDER BY ts DESC
        LIMIT 1
        """,
        (symbol,),
    )
    if not rows:
        return {"error": f"No recent strategy data for {symbol}."}
    return rows[0]


@mcp.tool()
def run_strategy_5_10_20() -> dict:
    """Run 5/10/20 MA strategy signals recording (calls record_strategy_signals(5))."""
    try:
        execute_write("SELECT record_strategy_signals(5)")
        return {"status": "ok", "message": "record_strategy_signals(5) executed successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def record_analysis(
    symbol: str,
    skill: str,
    as_of: str,
    horizon_days: int,
    direction: str,
    predicted: str,
    score: float,
    signal_type: str,
    entry_price: float,
) -> dict:
    """Insert a new analysis record.

    as_of: ISO date string e.g. '2025-01-15'
    direction: 'long' or 'short'
    signal_type: e.g. 'buy', 'watch', 'sell'
    """
    try:
        # Resolve skill_id if possible
        skill_rows = query_rows(
            "SELECT skill_id FROM skills WHERE family = %s AND status = 'champion' LIMIT 1",
            (skill,),
        )
        skill_id = skill_rows[0]["skill_id"] if skill_rows else None

        execute_write(
            """
            INSERT INTO analyses
              (symbol, skill, skill_id, as_of, horizon_days, due_date,
               direction, predicted, score, signal_type, entry_price)
            VALUES
              (%s, %s, %s, %s::date, %s, %s::date + %s,
               %s, %s, %s, %s, %s)
            """,
            (
                symbol, skill, skill_id, as_of, horizon_days, as_of, horizon_days,
                direction, predicted, score, signal_type, entry_price,
            ),
        )
        return {"status": "ok", "message": f"Analysis recorded for {symbol} ({skill})."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def evaluate_predictions() -> dict:
    """Evaluate due predictions by calling evaluate_due_predictions()."""
    try:
        execute_write("SELECT evaluate_due_predictions()")
        return {"status": "ok", "message": "evaluate_due_predictions() executed successfully."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_accuracy() -> list[dict]:
    """Get skill performance summary from v_skill_performance."""
    rows = query_rows("SELECT * FROM v_skill_performance ORDER BY win_rate DESC NULLS LAST")
    if not rows:
        return [{"message": "No skill performance data yet."}]
    return rows


@mcp.tool()
def upsert_skill(family: str, params_json: str, notes: str = "") -> dict:
    """Insert a new skill candidate (status='candidate'). LLM proposes; human promotes to champion.

    family: skill family name e.g. 'strategy_5_10_20'
    params_json: JSON string of parameters e.g. '{"fast": 5, "slow": 20}'
    notes: optional description
    """
    try:
        params_dict = json.loads(params_json)
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"Invalid params_json: {e}"}

    try:
        # Compute a simple param_hash for dedup
        import hashlib
        param_hash = hashlib.md5(json.dumps(params_dict, sort_keys=True).encode()).hexdigest()

        execute_write(
            """
            INSERT INTO skills (family, version, status, params, param_hash, notes, created_by)
            VALUES (
                %s,
                COALESCE(
                    (SELECT MAX(version) + 1 FROM skills WHERE family = %s),
                    1
                ),
                'candidate',
                %s::jsonb,
                %s,
                %s,
                'llm'
            )
            ON CONFLICT (family, param_hash) DO UPDATE
              SET notes = EXCLUDED.notes
            """,
            (family, family, json.dumps(params_dict), param_hash, notes),
        )
        return {
            "status": "ok",
            "message": f"Skill candidate upserted for family '{family}'.",
            "note": "Status set to 'candidate'. Promote to 'champion' manually after evaluation.",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool()
def get_vcp_watchlist() -> dict:
    """今日 VCP 突破監控清單（接近樞紐、收縮完成的 VCP 候選股）。

    回傳最新 scan_date 的清單，依分數排序。
    status='剛突破' 為可進場買點；'待突破'/'待突破(量縮)' 為接近樞紐、盯著等放量突破。
    distance_pct 為距樞紐百分比（負=已突破、正=尚未突破）。
    """
    try:
        rows = query_rows(
            "SELECT scan_date, symbol, name, score, status, distance_pct, "
            "       contraction_count, last_drawdown_pct, close, pivot "
            "FROM vcp_watchlist "
            "WHERE scan_date = (SELECT max(scan_date) FROM vcp_watchlist) "
            "ORDER BY score DESC, distance_pct ASC"
        )
        return {
            "scan_date": str(rows[0]["scan_date"]) if rows else None,
            "count": len(rows),
            "watchlist": rows,
        }
    except Exception as e:
        return {"status": "error", "message": str(e),
                "hint": "vcp_watchlist 表可能尚未建立或當日無候選"}


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("Starting stock-ai FastMCP server on 0.0.0.0:8000")
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
