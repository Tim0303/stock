"""
智能 AI 選股平台 — FastAPI 唯讀 REST (api-agent / T10)
路由前綴 /api；角色 stock_readonly（唯讀）；容器內 8000，對外 7003。
OpenAPI 自動產生：/docs、/openapi.json 供前端 T11 對齊契約。
"""

import os
from contextlib import asynccontextmanager
from typing import Any

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

DATABASE_URL = os.environ["DATABASE_URL"]


# ── DB 連線工廠（每請求短連線，無需 pool；唯讀負載低）──────────────────────
def get_conn():
    return psycopg2.connect(DATABASE_URL)


def query(sql: str, params=None) -> list[dict]:
    """執行 SQL，回傳 list[dict]（欄位名稱 key）。"""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or ())
            return [dict(r) for r in cur.fetchall()]


def table_exists(conn, table_name: str) -> bool:
    """檢查 table / view 是否存在（to_regclass）。"""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (table_name,))
        return cur.fetchone()[0] is not None


# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="智能 AI 選股平台 API",
    description=(
        "唯讀 REST，供前端戰情儀表板使用。\n\n"
        "角色：`stock_readonly`（PostgreSQL 唯讀）。\n"
        "所有路由掛在 `/api` 前綴，配合 nginx 反代同源。"
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# ── /api/health ───────────────────────────────────────────────────────────────
@app.get(
    "/api/health",
    summary="健康檢查",
    tags=["infra"],
    response_description="服務與 DB 連線狀態",
)
def health():
    """回傳 {status: ok}；同時驗證 DB 可連。"""
    try:
        query("SELECT 1")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB unreachable: {exc}")
    return {"status": "ok"}


# ── /api/candidates ───────────────────────────────────────────────────────────
@app.get(
    "/api/candidates",
    summary="選股候選清單",
    tags=["strategy"],
    response_description="依分數排序的買入/觀察清單",
)
def candidates(
    market: str = Query(default="", description="市場篩選：TW / US；空字串 = 全部"),
    limit: int = Query(default=30, ge=1, le=200, description="最多回傳筆數"),
):
    """
    優先讀 `daily_candidates` 表；若該表不存在（另一 agent 尚未建立）則
    fallback 到 `v_strategy_latest`，取近期 buy/watch 訊號（依 score DESC）。

    殭屍股過濾：`ts >= max(ts) - 5 days`。
    """
    try:
        conn = get_conn()
        use_daily_candidates = table_exists(conn, "daily_candidates")
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB error: {exc}")

    if use_daily_candidates:
        # daily_candidates 由 scanner-agent 維護；
        # PK (scan_date, symbol)，用 scan_date 做殭屍股過濾。
        market_filter = "AND dc.market = %(market)s" if market else ""
        sql = f"""
            SELECT
                dc.scan_date,
                dc.symbol,
                sym.name,
                dc.market,
                sym.industry_category,
                dc.score,
                dc.rating,
                dc.signal_type,
                dc.rank,
                dc.skill_id
            FROM daily_candidates dc
            LEFT JOIN symbols sym USING (symbol)
            WHERE dc.scan_date >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
              {market_filter}
            ORDER BY dc.score DESC
            LIMIT %(limit)s
        """
        params: dict[str, Any] = {"limit": limit}
        if market:
            params["market"] = market
        source = "daily_candidates"
    else:
        # Fallback：v_strategy_latest JOIN symbols 取市場欄位
        market_filter = "AND s.market = %(market)s" if market else ""
        sql = f"""
            SELECT
                vl.symbol,
                sym.name,
                sym.market,
                sym.industry_category,
                vl.ts,
                vl.close,
                vl.score,
                vl.signal_type,
                vl.rating,
                vl.ma5,
                vl.ma10,
                vl.ma20,
                vl.bias_ma10,
                vl.bias_ma20,
                vl.bull_align,
                vl.filtered
            FROM v_strategy_latest vl
            JOIN symbols sym USING (symbol)
            WHERE vl.rating IN ('buy', 'watch')
              AND vl.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
              {market_filter}
            ORDER BY vl.score DESC
            LIMIT %(limit)s
        """
        params = {"limit": limit}
        if market:
            params["market"] = market
        source = "v_strategy_latest (fallback)"

    try:
        rows = query(sql, params)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"source": source, "count": len(rows), "data": rows}


# ── /api/accuracy ─────────────────────────────────────────────────────────────
@app.get(
    "/api/accuracy",
    summary="三方分析師準確率（技能績效）",
    tags=["performance"],
    response_description="各 skill 的評估筆數、勝率、平均報酬、獲利因子",
)
def accuracy():
    """
    讀 `v_skill_performance`：每個 skill 家族的歷史評分統計。
    欄位：skill, n_evaluated, win_rate, avg_return, profit_factor。
    """
    try:
        rows = query(
            """
            SELECT skill, n_evaluated, win_rate, avg_return, profit_factor
            FROM v_skill_performance
            ORDER BY win_rate DESC NULLS LAST
            """
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"count": len(rows), "data": rows}


# ── /api/indicators/{symbol} ──────────────────────────────────────────────────
@app.get(
    "/api/indicators/{symbol}",
    summary="技術指標（均線 / 量能 / 乖離）",
    tags=["indicators"],
    response_description="近 N 日的 MA5/10/20、vol_ma5、bias、prev_high_5 等",
)
def indicators(
    symbol: str,
    limit: int = Query(default=60, ge=1, le=500, description="回傳最近 N 個交易日"),
):
    """
    讀 `v_price_indicators`，回傳指定標的近 N 日技術指標。
    欄位包含：ts, open, high, low, close, volume, ma5, ma10, ma20,
    vol_ma5, prev_high_5, bias_ma10, bias_ma20, close_prev, n_window。
    """
    try:
        rows = query(
            """
            SELECT *
            FROM v_price_indicators
            WHERE symbol = %(symbol)s
            ORDER BY ts DESC
            LIMIT %(limit)s
            """,
            {"symbol": symbol, "limit": limit},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not rows:
        raise HTTPException(status_code=404, detail=f"symbol '{symbol}' not found or no data")
    return {"symbol": symbol, "count": len(rows), "data": rows}


# ── /api/strategy/{symbol} ────────────────────────────────────────────────────
@app.get(
    "/api/strategy/{symbol}",
    summary="5-10-20 策略訊號",
    tags=["strategy"],
    response_description="近 N 日的策略訊號、評分、rating",
)
def strategy(
    symbol: str,
    limit: int = Query(default=60, ge=1, le=500, description="回傳最近 N 個交易日"),
):
    """
    讀 `v_strategy_5_10_20`，回傳指定標的近 N 日的策略計算結果。
    欄位包含：ts, close, score, signal_type (A/B/C), rating (buy/watch/skip/avoid),
    bull_align, sig_a, sig_b, sig_c, filtered, horizon_days 等。
    """
    try:
        rows = query(
            """
            SELECT *
            FROM v_strategy_5_10_20
            WHERE symbol = %(symbol)s
            ORDER BY ts DESC
            LIMIT %(limit)s
            """,
            {"symbol": symbol, "limit": limit},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if not rows:
        raise HTTPException(status_code=404, detail=f"symbol '{symbol}' not found or no strategy data")
    return {"symbol": symbol, "count": len(rows), "data": rows}


# ── /api/skills ───────────────────────────────────────────────────────────────
@app.get(
    "/api/skills",
    summary="技能（策略）庫",
    tags=["skills"],
    response_description="所有技能的 family/version/status 與績效快照",
)
def skills():
    """
    讀 `skills` 表。回傳 family, version, status, market_scope, params,
    n_predictions, win_rate, avg_return, profit_factor, payoff_ratio,
    sharpe_like, max_drawdown, oos_win_rate, last_evaluated_at, notes。
    """
    try:
        rows = query(
            """
            SELECT
                skill_id, family, version, status, market_scope, params,
                n_predictions, win_rate, avg_return, profit_factor,
                payoff_ratio, sharpe_like, max_drawdown, oos_win_rate,
                last_evaluated_at, created_by, notes, created_at
            FROM skills
            ORDER BY family, version DESC
            """
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"count": len(rows), "data": rows}


# ── /api/chips/{symbol} ───────────────────────────────────────────────────────
@app.get(
    "/api/chips/{symbol}",
    summary="台股籌碼（三大法人 + 融資券）",
    tags=["chips"],
    response_description="近期籌碼資料；表不存在時回空陣列（容錯）",
)
def chips(
    symbol: str,
    limit: int = Query(default=30, ge=1, le=200, description="回傳最近 N 日"),
):
    """
    讀 `chip_institutional`（三大法人淨買超）與 `chip_margin`（融資券餘額）。
    以 ts LEFT JOIN 合併；若任一表不存在則該欄位為 null，整表不存在時回空陣列（容錯）。
    """
    try:
        conn = get_conn()
        has_inst = table_exists(conn, "chip_institutional")
        has_marg = table_exists(conn, "chip_margin")
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB error: {exc}")

    if not has_inst and not has_marg:
        return {"symbol": symbol, "count": 0, "data": [], "note": "chip tables not yet available"}

    if has_inst and has_marg:
        sql = """
            SELECT
                COALESCE(ci.ts, cm.ts)          AS ts,
                ci.foreign_net, ci.trust_net, ci.dealer_net, ci.total_net,
                cm.margin_balance, cm.margin_change,
                cm.short_balance,  cm.short_change
            FROM chip_institutional ci
            FULL OUTER JOIN chip_margin cm
                ON ci.symbol = cm.symbol AND ci.ts = cm.ts
            WHERE COALESCE(ci.symbol, cm.symbol) = %(symbol)s
            ORDER BY ts DESC
            LIMIT %(limit)s
        """
    elif has_inst:
        sql = """
            SELECT ts, foreign_net, trust_net, dealer_net, total_net
            FROM chip_institutional
            WHERE symbol = %(symbol)s
            ORDER BY ts DESC
            LIMIT %(limit)s
        """
    else:
        sql = """
            SELECT ts, margin_balance, margin_change, short_balance, short_change
            FROM chip_margin
            WHERE symbol = %(symbol)s
            ORDER BY ts DESC
            LIMIT %(limit)s
        """

    try:
        rows = query(sql, {"symbol": symbol, "limit": limit})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"symbol": symbol, "count": len(rows), "data": rows}
