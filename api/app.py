"""
智能 AI 選股平台 — FastAPI 唯讀 REST (api-agent / T10)
路由前綴 /api；角色 stock_readonly（唯讀）；容器內 8000，對外 7003。
OpenAPI 自動產生：/docs、/openapi.json 供前端 T11 對齊契約。
"""

import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any

import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

DATABASE_URL = os.environ["DATABASE_URL"]

# analyst-picks 涉及昂貴的策略 view（v_strategy_latest/box 是全歷史 DISTINCT ON 掃描，
# 單查可達數十秒甚至數分鐘，會把 DB CPU 打到 100%）。因此：
#   1. 絕不在請求路徑上同步計算——端點永遠立即回傳「最近一次快照」。
#   2. 由背景 thread 定時（啟動時 + 每 _ANALYST_REFRESH_SEC）重算一次快照。
#   3. 每條 SQL 加 statement_timeout，超時的分析師 graceful 回 count:0（不卡死、不爆 CPU）。
_ANALYST_CACHE: dict[str, Any] = {"ts": 0.0, "data": None, "computing": False}
_ANALYST_REFRESH_SEC = 600  # 背景重算間隔（10 分鐘）；策略訊號日內不變，無需頻繁重算
_ANALYST_STMT_TIMEOUT_MS = 45000  # 單條 SQL 上限，避免單查拖垮 DB
_ANALYST_LOCK = threading.Lock()


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
            WHERE skill NOT IN ('baseline-momentum','strat-box')  -- 已退役分析師
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
            WHERE family NOT IN ('baseline-momentum','strat-box')  -- 已退役分析師
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


# ── /api/vcp-watchlist ────────────────────────────────────────────────────────
@app.get(
    "/api/vcp-watchlist",
    summary="VCP 突破監控清單（第五分析師）",
    tags=["strategy"],
    response_description="最新 scan_date 的 VCP 候選監控清單，依 score 排序",
)
def vcp_watchlist():
    """
    讀 `vcp_watchlist` 表的**最新 scan_date** 清單，依 score DESC 排序。
    由 vcp watchlist 子命令寫入；表不存在時回空陣列（容錯）。
    回傳：{scan_date, count, data:[...]}。
    """
    try:
        conn = get_conn()
        has_table = table_exists(conn, "vcp_watchlist")
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB error: {exc}")

    if not has_table:
        return {"scan_date": None, "count": 0, "data": [],
                "note": "vcp_watchlist table not yet available"}

    try:
        rows = query(
            """
            SELECT
                scan_date, symbol, name, close, pivot, distance_pct,
                contraction_count, last_drawdown_pct, score, status, vol_dry
            FROM vcp_watchlist
            -- 近期防呆：只取最近 7 日內的快照，避免掃描無候選時退回顯示遠古舊清單
            WHERE scan_date = (
                SELECT max(scan_date) FROM vcp_watchlist
                WHERE scan_date >= (SELECT max(ts)::date FROM daily_prices) - 7
            )
            ORDER BY score DESC NULLS LAST, distance_pct ASC
            """
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    scan_date = rows[0]["scan_date"] if rows else None
    return {"scan_date": scan_date, "count": len(rows), "data": rows}


# ── /api/eod-signals ──────────────────────────────────────────────────────────
@app.get(
    "/api/eod-signals",
    summary="尾盤即時訊號（盤中掃描快照）",
    tags=["strategy"],
    response_description="最新一次盤中掃描（預設 13:10）凍結的買進候選，依分析師分組",
)
def eod_signals(limit: int = Query(default=200, ge=1, le=500)):
    """
    讀 `eod_intraday_signals` 的**最新 scan_time** 快照（盤中以即時報價算出的今日候選）。
    表不存在 / 尚無掃描時回空（容錯）。回傳：{scan_time, scan_date, count, data:[...]}。
    純預覽（不寫 analyses）；正式記錄仍由 15:00 收盤那班負責。
    """
    try:
        conn = get_conn()
        has_table = table_exists(conn, "eod_intraday_signals")
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB error: {exc}")

    if not has_table:
        return {"scan_time": None, "scan_date": None, "count": 0, "data": [],
                "note": "eod_intraday_signals table not yet available"}

    try:
        rows = query(
            """
            SELECT skill, symbol, name, score, signal_type,
                   close, entry_price, target_price, stop_price, meta,
                   scan_time, scan_date
            FROM eod_intraday_signals
            WHERE scan_time = (SELECT max(scan_time) FROM eod_intraday_signals)
            ORDER BY skill, score DESC NULLS LAST
            LIMIT %(limit)s
            """,
            {"limit": limit},
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    scan_time = rows[0]["scan_time"].isoformat() if rows else None
    scan_date = rows[0]["scan_date"] if rows else None
    return {"scan_time": scan_time, "scan_date": scan_date, "count": len(rows), "data": rows}


# ── /api/symbols ──────────────────────────────────────────────────────────────
@app.get(
    "/api/symbols",
    summary="標的清單（自動完成用）",
    tags=["infra"],
    response_description="symbol / name / market 清單，供前端個股查詢自動完成",
)
def symbols(
    market: str = Query(default="", description="市場篩選：TW / US；空字串 = 全部"),
    limit: int = Query(default=2000, ge=1, le=10000, description="最多回傳筆數"),
):
    """
    讀 `symbols` 表，回傳 symbol, name, market。供 ChartPanel datalist 自動完成。
    優先列出有日K資料的標的（INNER 視 daily_prices）。表不存在時回空陣列（容錯）。
    """
    try:
        conn = get_conn()
        has_table = table_exists(conn, "symbols")
        conn.close()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"DB error: {exc}")

    if not has_table:
        return {"count": 0, "data": [], "note": "symbols table not available"}

    market_filter = "WHERE market = %(market)s" if market else ""
    sql = f"""
        SELECT symbol, name, market
        FROM symbols
        {market_filter}
        ORDER BY symbol
        LIMIT %(limit)s
    """
    params: dict[str, Any] = {"limit": limit}
    if market:
        params["market"] = market
    try:
        rows = query(sql, params)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"count": len(rows), "data": rows}


# ── /api/analyst-picks ────────────────────────────────────────────────────────
def _safe_picks(conn, table_or_view: str, sql: str, params=None) -> list[dict]:
    """若來源表/視圖不存在回 []，查詢失敗/逾時也回 []（個別分析師容錯，不拖垮整個端點）。

    每條查詢套用 statement_timeout（local，僅本交易），確保慢如箱型 view 也能被
    強制中止，避免把 DB CPU 打滿。逾時的分析師 graceful 回空清單（count:0）。
    """
    try:
        if not table_exists(conn, table_or_view):
            return []
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout = %s", (_ANALYST_STMT_TIMEOUT_MS,))
            cur.execute(sql, params or {})
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        # 個別分析師查詢失敗/逾時不應導致 500；回空清單並標 count:0
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def _compute_analyst_picks() -> dict:
    """實際查 5 位分析師最新推薦（昂貴；僅由背景 refresher 呼叫，絕不在請求路徑同步執行）。"""
    conn = get_conn()
    # 用顯式交易塊讓 SET LOCAL statement_timeout 生效（autocommit 下 LOCAL 無作用）
    conn.autocommit = False

    analysts = []

    # ── 1. strat-vcp ──────────────────────────────────────────────────────────
    vcp_rows = _safe_picks(
        conn,
        "vcp_watchlist",
        """
        SELECT symbol, name, score, status, distance_pct
        FROM vcp_watchlist
        WHERE scan_date = (
            SELECT max(scan_date) FROM vcp_watchlist
            WHERE scan_date >= (SELECT max(ts)::date FROM daily_prices) - 7
        )
        ORDER BY score DESC NULLS LAST, distance_pct ASC
        """,
    )
    vcp_as_of = None
    try:
        if table_exists(conn, "vcp_watchlist"):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT max(scan_date) FROM vcp_watchlist "
                    "WHERE scan_date >= (SELECT max(ts)::date FROM daily_prices) - 7"
                )
                r = cur.fetchone()
                vcp_as_of = r[0].isoformat() if r and r[0] else None
    except Exception:
        conn.rollback()
    analysts.append({
        "skill": "strat-vcp",
        "label": "VCP 突破",
        "as_of": vcp_as_of,
        "count": len(vcp_rows),
        "picks": [
            {
                "symbol": r["symbol"],
                "name": r.get("name"),
                "score": r.get("score"),
                "extra": {"status": r.get("status"), "distance_pct": r.get("distance_pct")},
            }
            for r in vcp_rows
        ],
    })

    # ── 2. strat-5-10-20 ──────────────────────────────────────────────────────
    s510_rows = _safe_picks(
        conn,
        "v_strategy_latest",
        """
        SELECT l.symbol, sy.name, l.score, l.signal_type, l.close AS entry_price,
               l.target_price, l.stop_price, l.target_pct, l.ts AS as_of
        FROM v_strategy_latest l
        JOIN symbols sy USING (symbol)
        WHERE l.rating = 'buy'
          AND l.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
        ORDER BY l.score DESC NULLS LAST
        """,
    )
    s510_as_of = s510_rows[0]["as_of"].isoformat() if s510_rows and s510_rows[0].get("as_of") else None
    analysts.append({
        "skill": "strat-5-10-20",
        "label": "5-10-20 順勢",
        "as_of": s510_as_of,
        "count": len(s510_rows),
        "picks": [
            {
                "symbol": r["symbol"],
                "name": r.get("name"),
                "score": r.get("score"),
                "extra": {
                    "signal_type": r.get("signal_type"),
                    "entry_price": r.get("entry_price"),
                    "target_price": r.get("target_price"),
                    "stop_price": r.get("stop_price"),
                    "target_pct": r.get("target_pct"),
                },
            }
            for r in s510_rows
        ],
    })

    # ── strat-box 已退役（長期 PF≈1.0、擴樣後走弱，使用者決定移除；view/資料保留）──

    # ── 破支撐拉回 strat-spring（v_support_reclaim_latest）──────────────────
    spring_rows = _safe_picks(
        conn,
        "v_support_reclaim_latest",
        """
        SELECT r.symbol, sy.name, r.score, r.above_sup_pct, r.close AS entry_price,
               r.target_price, r.stop_price, r.target_pct, r.ts AS as_of
        FROM v_support_reclaim_latest r
        JOIN symbols sy USING (symbol)
        WHERE r.signal_type = 'spring'
          AND r.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
        ORDER BY r.score DESC NULLS LAST
        """,
    )
    spring_as_of = spring_rows[0]["as_of"].isoformat() if spring_rows and spring_rows[0].get("as_of") else None
    analysts.append({
        "skill": "strat-spring",
        "label": "破支撐拉回",
        "as_of": spring_as_of,
        "count": len(spring_rows),
        "picks": [
            {
                "symbol": r["symbol"],
                "name": r.get("name"),
                "score": r.get("score"),
                "extra": {
                    "above_sup_pct": r.get("above_sup_pct"),
                    "entry_price": r.get("entry_price"),
                    "target_price": r.get("target_price"),
                    "stop_price": r.get("stop_price"),
                    "target_pct": r.get("target_pct"),
                },
            }
            for r in spring_rows
        ],
    })

    # ── 5. strat-bb-trend 布林通道趨勢續抱（進場=5-10-20、出場=趨勢續抱）─────────────
    bb_rows = _safe_picks(
        conn,
        "v_bb_trend_latest",
        """
        SELECT l.symbol, sy.name, l.score, l.signal_type,
               l.entry_price, l.stop_price, l.exit_rule, l.ts AS as_of
        FROM v_bb_trend_latest l
        JOIN symbols sy USING (symbol)
        WHERE l.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
        ORDER BY l.score DESC NULLS LAST
        """,
    )
    bb_as_of = bb_rows[0]["as_of"].isoformat() if bb_rows and bb_rows[0].get("as_of") else None
    analysts.append({
        "skill": "strat-bb-trend",
        "label": "布林通道趨勢續抱",
        "as_of": bb_as_of,
        "count": len(bb_rows),
        "picks": [
            {
                "symbol": r["symbol"],
                "name": r.get("name"),
                "score": r.get("score"),
                "extra": {
                    "signal_type": r.get("signal_type"),
                    "entry_price": r.get("entry_price"),
                    "stop_price": r.get("stop_price"),
                    "exit_rule": r.get("exit_rule"),
                },
            }
            for r in bb_rows
        ],
    })

    # ── 6. strat-bb-breakout 布林開口放量突破（出場=跌破20MA單一標準）────────────
    bbk_rows = _safe_picks(
        conn,
        "v_bb_breakout_latest",
        """
        SELECT l.symbol, sy.name, l.score, l.signal_type,
               l.entry_price, l.vol_ratio, l.bw_ratio, l.exit_rule, l.ts AS as_of
        FROM v_bb_breakout_latest l
        JOIN symbols sy USING (symbol)
        ORDER BY l.score DESC NULLS LAST
        """,
    )
    bbk_as_of = bbk_rows[0]["as_of"].isoformat() if bbk_rows and bbk_rows[0].get("as_of") else None
    analysts.append({
        "skill": "strat-bb-breakout",
        "label": "布林開口放量突破",
        "as_of": bbk_as_of,
        "count": len(bbk_rows),
        "picks": [
            {
                "symbol": r["symbol"],
                "name": r.get("name"),
                "score": r.get("score"),
                "extra": {
                    "signal_type": r.get("signal_type"),
                    "entry_price": r.get("entry_price"),
                    "vol_ratio": r.get("vol_ratio"),
                    "bw_ratio": r.get("bw_ratio"),
                    "exit_rule": r.get("exit_rule"),
                },
            }
            for r in bbk_rows
        ],
    })

    # ── 7. ml-logreg (analyses) ───────────────────────────────────────────────
    # 註：baseline-momentum（動能對照）已於使用者要求下移除（純對照、無實用價值）。
    for skill_id, label in [
        ("ml-logreg", "ML 預測"),
    ]:
        rows = _safe_picks(
            conn,
            "analyses",
            """
            SELECT a.symbol, sy.name, a.score, a.as_of
            FROM analyses a
            JOIN symbols sy USING (symbol)
            WHERE a.skill = %(skill)s
              AND (a.meta->>'backtest') IS DISTINCT FROM 'true'
              AND a.predicted = 'up'
              AND a.as_of = (
                  SELECT max(as_of) FROM analyses
                  WHERE skill = %(skill)s
                    AND (meta->>'backtest') IS DISTINCT FROM 'true'
              )
            ORDER BY a.score DESC NULLS LAST
            """,
            {"skill": skill_id},
        )
        as_of = rows[0]["as_of"].isoformat() if rows and rows[0].get("as_of") else None
        analysts.append({
            "skill": skill_id,
            "label": label,
            "as_of": as_of,
            "count": len(rows),
            "picks": [
                {
                    "symbol": r["symbol"],
                    "name": r.get("name"),
                    "score": r.get("score"),
                    "extra": {},
                }
                for r in rows
            ],
        })

    # 大盤體質（寬度）；策略類分析師在 market_ok=false 時不開倉（空頭過濾）
    market = None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ts, breadth_pct, market_ok FROM v_market_regime ORDER BY ts DESC LIMIT 1")
            r = cur.fetchone()
            if r:
                market = {"ts": r[0].isoformat(), "breadth_pct": float(r[1]), "market_ok": bool(r[2])}
    except Exception:
        conn.rollback()

    try:
        conn.rollback()  # 唯讀，無需 commit；結束交易並釋放連線
    except Exception:
        pass
    conn.close()
    return {"analysts": analysts, "market": market}


def _refresh_analyst_cache():
    """背景重算快照；以 lock 確保同時只有一次重算。失敗則保留舊快照。"""
    if not _ANALYST_LOCK.acquire(blocking=False):
        return  # 已有重算進行中
    try:
        _ANALYST_CACHE["computing"] = True
        result = _compute_analyst_picks()
        _ANALYST_CACHE["data"] = result
        _ANALYST_CACHE["ts"] = time.time()
    except Exception:
        # 重算失敗保留舊快照；不拋出（背景 thread）
        pass
    finally:
        _ANALYST_CACHE["computing"] = False
        _ANALYST_LOCK.release()


def _analyst_refresh_loop():
    """背景常駐：啟動時算一次，之後每 _ANALYST_REFRESH_SEC 重算一次。"""
    while True:
        _refresh_analyst_cache()
        time.sleep(_ANALYST_REFRESH_SEC)


@app.on_event("startup")
def _start_analyst_refresher():
    t = threading.Thread(target=_analyst_refresh_loop, daemon=True, name="analyst-refresher")
    t.start()


@app.get(
    "/api/analyst-picks",
    summary="5 位分析師各自最新推薦（個別列出）",
    tags=["strategy"],
    response_description="5 位分析師各自的最新推薦標的，含 0 檔時也回傳空 picks",
)
def analyst_picks(
    refresh: bool = Query(default=False, description="觸發背景重算（非同步，立即回傳現有快照）"),
):
    """
    回傳 5 位分析師各自最新一輪推薦：
      1. strat-vcp        — VCP 突破（vcp_watchlist 最新 scan_date）
      2. strat-5-10-20    — 5-10-20 順勢（v_strategy_latest buy）
      3. strat-box        — 箱型區間（v_strategy_box_latest buy_signal）
      4. baseline-momentum— 動能對照（analyses）
      5. ml-logreg        — ML 預測（analyses）
    每位分析師即使 0 檔也回 {count:0, picks:[]}，由前端顯示「今日無推薦」。

    ⚠ 策略 view（v_strategy_latest/box）為全歷史掃描、可達數十秒，會把 DB CPU 打滿，
    故此端點**永不在請求路徑同步計算**：由背景 thread 每 10 分鐘重算快照，端點立即回傳
    最近一次快照。冷啟動快照尚未就緒時回 {stale:true, computing:true, analysts:[]}。
    """
    if refresh and not _ANALYST_CACHE["computing"]:
        # 觸發一次背景重算（非阻塞），仍立即回傳現有快照
        threading.Thread(target=_refresh_analyst_cache, daemon=True).start()

    data = _ANALYST_CACHE["data"]
    if data is None:
        return {
            "analysts": [],
            "stale": True,
            "computing": _ANALYST_CACHE["computing"],
            "note": "snapshot 計算中，請稍候（背景首次計算策略 view 較久）",
        }
    age = time.time() - _ANALYST_CACHE["ts"]
    return {**data, "stale": age > _ANALYST_REFRESH_SEC * 1.5, "as_of_epoch": _ANALYST_CACHE["ts"]}
