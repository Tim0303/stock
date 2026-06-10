"""
main.py — strat-vcp（第五分析師）進入點。VCP 波動收縮型態選股（Minervini SEPA 風格）。

子命令：
  scan       近期掃描：對最新交易日附近（ts >= max(ts)-5 日）出現的「突破買訊號」
             寫入 analyses（skill='strat-vcp'）。
  bootstrap  歷史回填：對歷史所有「突破買訊號日」寫 analyses（meta backtest），
             讓 evaluate_due_predictions() 能評分、v_skill_performance 出現 strat-vcp。
  backtest   VCP 進出場回測：突破進場（突破日 close），最早觸發
             「跌破最後一次收縮低點」或「跌破進場價*(1-停損)」即出場，
             扣 0.6% 成本，印 PF / 勝率 / 平均持有。

平台契約：
  - 只 INSERT analyses，不改表、不刪資料。
  - 還原價：所有 OHLC * adj_factor。
  - horizon_days=5；due_date = as_of + 7 日曆日。entry_price = 還原 close（突破日）。
  - skill_id 指向 strat-vcp champion（family='strat-vcp', version=1, status='champion'）。

無前視保證見 vcp_core.py 模組註解：swing 點需 i+swing_window<=d 才採用，
pivot/contraction 皆不含 d 之後資料；進場用突破日 close（當日可知），
出場每日重算只用到該日為止。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import timedelta

import numpy as np
import pandas as pd
import psycopg2

from vcp_core import DEFAULT_PARAMS, detect_vcp_at

HORIZON_DAYS = DEFAULT_PARAMS["horizon_days"]            # 5
DUE_OFFSET_DAYS = 7                                      # as_of + 7 日曆日
COST = 0.006                                             # 回測來回成本 0.6%
SKILL = "strat-vcp"
PARAM_HASH = "seed-vcp-v1"


def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[error] DATABASE_URL 未設定", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(url)


# --------------------------------------------------------------------------- #
# champion skill
# --------------------------------------------------------------------------- #
def ensure_champion(conn) -> int:
    """確保 strat-vcp champion 存在（規格第 11 節預設參數），回傳 skill_id。"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT skill_id FROM skills WHERE family=%s AND param_hash=%s",
            (SKILL, PARAM_HASH),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute(
            """INSERT INTO skills
                 (family, version, status, market_scope, params, param_hash, created_by, notes)
               VALUES (%s, 1, 'champion', 'TW', %s::jsonb, %s, 'system', %s)
               RETURNING skill_id""",
            (SKILL, json.dumps(DEFAULT_PARAMS), PARAM_HASH,
             "VCP 波動收縮型態選股（Minervini SEPA），突破樞紐點放量為買訊號"),
        )
        skill_id = int(cur.fetchone()[0])
    conn.commit()
    print(f"[skill] 建立 strat-vcp champion skill_id={skill_id}")
    return skill_id


# --------------------------------------------------------------------------- #
# 資料載入（還原價）
# --------------------------------------------------------------------------- #
def load_symbols(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM symbols WHERE market='TW' ORDER BY symbol")
        return [r[0] for r in cur.fetchall()]


def load_prices(conn, symbol) -> pd.DataFrame:
    """還原權值 OHLCV，依 ts 升冪。"""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT ts,
                      open*adj_factor, high*adj_factor, low*adj_factor,
                      close*adj_factor, volume
               FROM daily_prices WHERE symbol=%s ORDER BY ts""",
            (symbol,),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def to_arrays(df):
    return (
        df["ts"].to_numpy(),
        df["open"].to_numpy(dtype=float),
        df["high"].to_numpy(dtype=float),
        df["low"].to_numpy(dtype=float),
        df["close"].to_numpy(dtype=float),
        df["volume"].to_numpy(dtype=float),
    )


# --------------------------------------------------------------------------- #
# analyses INSERT
# --------------------------------------------------------------------------- #
_INSERT_SQL = """
    INSERT INTO analyses
        (symbol, skill, skill_id, as_of, horizon_days, due_date,
         direction, predicted, score, signal_type, entry_price, meta)
    VALUES
        (%(symbol)s, %(skill)s, %(skill_id)s, %(as_of)s, %(horizon_days)s, %(due_date)s,
         'long', 'up', %(score)s, %(signal_type)s, %(entry_price)s, %(meta)s::jsonb)
"""


def _due_date(as_of_ts):
    return (pd.Timestamp(as_of_ts) + timedelta(days=DUE_OFFSET_DAYS)).date()


def _signal_row(symbol, skill_id, ts, res, backtest):
    meta = {
        "contraction_count": res.contraction_count,
        "drawdowns": res.drawdowns,
        "durations": res.durations,
        "last_drawdown": round(res.last_drawdown, 4) if not np.isnan(res.last_drawdown) else None,
        "pivot_price": round(res.pivot_price, 4) if not np.isnan(res.pivot_price) else None,
        "volume_dry_up": res.volume_dry_up,
    }
    if backtest:
        meta["backtest"] = True
    return {
        "symbol": symbol,
        "skill": SKILL,
        "skill_id": skill_id,
        "as_of": pd.Timestamp(ts).date(),
        "horizon_days": HORIZON_DAYS,
        "due_date": _due_date(ts),
        "score": round(float(res.score), 4),
        "signal_type": "vcp_breakout",
        "entry_price": round(float(res.close), 4),
        "meta": json.dumps(meta),
    }


def _existing_keys(conn, backtest):
    """已存在的 (symbol, as_of) 集合，避免重複寫入。"""
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, as_of FROM analyses WHERE skill=%s", (SKILL,))
        return {(s, a) for (s, a) in cur.fetchall()}


# --------------------------------------------------------------------------- #
# 偵測所有突破訊號日（共用於 scan / bootstrap / backtest）
# --------------------------------------------------------------------------- #
def find_signals(df, min_d=200, start_idx=None):
    """回傳該檔所有突破買訊號 [(idx, VCPResult)]。"""
    ts, o, h, l, c, v = to_arrays(df)
    n = len(c)
    out = []
    lo = max(min_d, start_idx if start_idx is not None else min_d)
    for d in range(lo, n):
        res = detect_vcp_at(ts, o, h, l, c, v, d)
        if res.breakout_signal:
            out.append((d, res))
    return out


# --------------------------------------------------------------------------- #
# scan
# --------------------------------------------------------------------------- #
def cmd_scan():
    conn = get_conn()
    try:
        skill_id = ensure_champion(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT max(ts) FROM daily_prices")
            max_ts = cur.fetchone()[0]
        cutoff = pd.Timestamp(max_ts) - timedelta(days=5)
        print(f"[scan] 最新交易日={max_ts}，掃描 ts>={cutoff.date()} 的突破訊號")

        existing = _existing_keys(conn, backtest=False)
        symbols = load_symbols(conn)
        rows = []
        for sym in symbols:
            df = load_prices(conn, sym)
            if len(df) < 201:
                continue
            ts, o, h, l, c, v = to_arrays(df)
            # 只對近 5 日的交易日做判定（但 detect 仍用其完整歷史，不偷看未來）
            for d in range(len(c) - 1, -1, -1):
                if pd.Timestamp(ts[d]) < cutoff:
                    break
                if d < 200:
                    continue
                res = detect_vcp_at(ts, o, h, l, c, v, d)
                if res.breakout_signal:
                    key = (sym, pd.Timestamp(ts[d]).date())
                    if key in existing:
                        continue
                    rows.append(_signal_row(sym, skill_id, ts[d], res, backtest=False))

        if rows:
            with conn.cursor() as cur:
                cur.executemany(_INSERT_SQL, rows)
            conn.commit()
        print(f"[scan] 寫入 {len(rows)} 筆突破訊號到 analyses")
        for r in rows[:20]:
            print(f"    {r['symbol']} {r['as_of']} score={r['score']} "
                  f"entry={r['entry_price']}")
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# bootstrap（歷史回填）
# --------------------------------------------------------------------------- #
def cmd_bootstrap():
    conn = get_conn()
    try:
        skill_id = ensure_champion(conn)
        existing = _existing_keys(conn, backtest=True)
        symbols = load_symbols(conn)
        total = 0
        for sym in symbols:
            df = load_prices(conn, sym)
            if len(df) < 201:
                continue
            sigs = find_signals(df)
            rows = []
            for d, res in sigs:
                ts_d = df["ts"].iloc[d]
                key = (sym, pd.Timestamp(ts_d).date())
                if key in existing:
                    continue
                rows.append(_signal_row(sym, skill_id, ts_d, res, backtest=True))
            if rows:
                with conn.cursor() as cur:
                    cur.executemany(_INSERT_SQL, rows)
                conn.commit()
                total += len(rows)
                print(f"[bootstrap] {sym}: +{len(rows)} 突破訊號")
        print(f"[bootstrap] 共寫入 {total} 筆歷史突破訊號 (meta backtest)")
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# backtest（VCP 專屬出場）
# --------------------------------------------------------------------------- #
def cmd_backtest():
    conn = get_conn()
    try:
        symbols = load_symbols(conn)
        trades = []   # dict: symbol, entry_date, exit_date, ret, hold_days, exit_reason
        for sym in symbols:
            df = load_prices(conn, sym)
            if len(df) < 201:
                continue
            ts, o, h, l, c, v = to_arrays(df)
            n = len(c)
            sigs = find_signals(df)
            for d, res in sigs:
                entry = float(c[d])
                stop = entry * (1 - DEFAULT_PARAMS["stop_loss_pct"])
                swing_low = res.last_swing_low
                # 出場：自 d+1 起每日只用到該日為止判斷
                exit_idx = None
                exit_reason = None
                exit_price = None
                for j in range(d + 1, n):
                    cj = float(c[j])
                    # 跌破最後收縮低點 或 跌破停損價（用當日收盤判定）
                    if not np.isnan(swing_low) and cj < swing_low:
                        exit_idx, exit_reason, exit_price = j, "break_swing_low", cj
                        break
                    if cj < stop:
                        exit_idx, exit_reason, exit_price = j, "stop_loss", cj
                        break
                if exit_idx is None:
                    # 未觸發出場：以最後一根收盤平倉（mark-to-market）
                    exit_idx, exit_reason, exit_price = n - 1, "open_end", float(c[n - 1])
                gross = exit_price / entry - 1
                net = gross - COST

                # horizon-capped 出場（公平比較用）：先觸發 stop/swing 則用之，
                # 否則最晚持有到 d+horizon 那天收盤平倉。皆只用 <= 出場日資料。
                cap_idx = min(exit_idx, d + HORIZON_DAYS, n - 1)
                ret_h = float(c[cap_idx]) / entry - 1 - COST

                trades.append({
                    "symbol": sym,
                    "entry_date": pd.Timestamp(ts[d]).date(),
                    "exit_date": pd.Timestamp(ts[exit_idx]).date(),
                    "ret": net,
                    "hold_days": exit_idx - d,
                    "exit_reason": exit_reason,
                    "ret_h": ret_h,
                    "hold_h": cap_idx - d,
                })
        _report_backtest(trades)
    finally:
        conn.close()


def _stats(trades, ret_key="ret", hold_key="hold_days"):
    rets = np.array([t[ret_key] for t in trades], dtype=float)
    holds = np.array([t[hold_key] for t in trades], dtype=float)
    wins = rets > 0
    gp = rets[rets > 0].sum()
    gl = -rets[rets < 0].sum()
    pf = gp / gl if gl > 0 else float("inf")
    avg_ret = rets.mean()
    avg_hold = holds.mean()
    return {
        "n": len(rets), "win_rate": wins.mean(), "pf": pf,
        "avg_ret": avg_ret, "avg_hold": avg_hold,
        "median_hold": float(np.median(holds)),
        "per_day": (avg_ret / avg_hold if avg_hold > 0 else float("nan")),
    }


def _print_stats(title, s):
    print(f"-- {title} --")
    print(f"   交易數 {s['n']} | 勝率 {s['win_rate']:.4f} | PF {s['pf']:.3f} | "
          f"avg_ret {s['avg_ret']:.4%} | avg_hold {s['avg_hold']:.1f}d | "
          f"med_hold {s['median_hold']:.0f}d | 報酬/日 {s['per_day']:.4%}")


def _report_backtest(trades):
    if not trades:
        print("[backtest] 無交易。")
        return
    from collections import Counter
    rc = Counter(t["exit_reason"] for t in trades)

    print("=" * 70)
    print("strat-vcp 回測（突破進場 / 跌破收縮低點或 -7% 停損出場，扣 0.6% 成本）")
    print("=" * 70)
    print(f"出場原因分布: {dict(rc)}")
    print()

    # (A) 自然出場（含 open_end 以資料末收盤 mark-to-market）—— 完整但受長尾影響
    print("(A) 自然出場（規則出場 + 未出場者以資料末收盤平倉）：")
    _print_stats("全部", _stats(trades))
    closed = [t for t in trades if t["exit_reason"] != "open_end"]
    if closed:
        _print_stats("僅已規則出場（排除 open_end，避免未實現長尾灌水）", _stats(closed))
    print()

    # (B) 持有期上限 = horizon_days（與其他策略對齊的公平比較）
    #     每筆若在出場前未達 horizon，則以 entry+horizon 那天收盤平倉。
    print(f"(B) 持有期 capped = horizon {HORIZON_DAYS} 日（與其他策略對齊的公平比較）：")
    _print_stats("capped", _stats(trades, ret_key="ret_h", hold_key="hold_h"))
    print()

    print("樣本交易（前 8 筆，自然出場）:")
    for t in trades[:8]:
        print(f"    {t['symbol']} {t['entry_date']}->{t['exit_date']} "
              f"ret={t['ret']:.4%} hold={t['hold_days']} {t['exit_reason']}")


# --------------------------------------------------------------------------- #
# watchlist — 今日「VCP 候選監控清單」（接近突破、該盯的；不寫 analyses，純監控）
# --------------------------------------------------------------------------- #
_WATCHLIST_UPSERT_SQL = """
    INSERT INTO vcp_watchlist
        (scan_date, symbol, name, close, pivot, distance_pct,
         contraction_count, last_drawdown_pct, score, status, vol_dry)
    VALUES
        (%(scan_date)s, %(symbol)s, %(name)s, %(close)s, %(pivot)s, %(distance_pct)s,
         %(contraction_count)s, %(last_drawdown_pct)s, %(score)s, %(status)s, %(vol_dry)s)
    ON CONFLICT (scan_date, symbol) DO UPDATE SET
        name              = EXCLUDED.name,
        close             = EXCLUDED.close,
        pivot             = EXCLUDED.pivot,
        distance_pct      = EXCLUDED.distance_pct,
        contraction_count = EXCLUDED.contraction_count,
        last_drawdown_pct = EXCLUDED.last_drawdown_pct,
        score             = EXCLUDED.score,
        status            = EXCLUDED.status,
        vol_dry           = EXCLUDED.vol_dry,
        created_at        = now()
"""


FORMING_DIST_MAX = 0.25      # 醞釀中：距樞紐 5%~25%（收縮成形中、尚未貼近 → 預測快形成 VCP）
FORMING_LAST_DD_MAX = 0.12   # 醞釀中末次回檔上限（比完整候選 0.10 略寬）


def _vcp_stage(res):
    """分類 VCP 階段，回傳 'breakout'/'near'/'forming' 或 None（不入清單）。
    - breakout/near：完整 VCP 候選（candidate_pass）且貼近或剛突破樞紐（距樞紐 -5%~+5%）。
    - forming（醞釀中）：趨勢成立 + 已有 ≥2 次「逐次變小」的回檔（VCP 雛形，比完整候選的
      0.65× 嚴格遞減寬鬆，只需非遞增）+ 末次回檔 ≤ 上限，但距樞紐仍 5%~25%（尚未貼近）
      → 早期預測「快形成 VCP」。不要求 time_compression。"""
    dp = res.distance_to_pivot
    if res.candidate_pass and not np.isnan(dp) and dp >= -0.05:
        return "breakout" if res.breakout else "near"
    dds = res.drawdowns
    loosely_contracting = len(dds) >= 2 and all(
        dds[k] <= dds[k - 1] + 1e-9 for k in range(1, len(dds)))
    if (res.stage2_pass and res.contraction_count >= 2
            and loosely_contracting
            and not np.isnan(res.last_drawdown)
            and res.last_drawdown <= FORMING_LAST_DD_MAX
            and not np.isnan(dp)
            and DEFAULT_PARAMS["near_pivot_pct"] < dp <= FORMING_DIST_MAX):
        return "forming"
    return None


def _watchlist_status(row):
    """中文狀態：剛突破 / 待突破(量縮) / 待突破 / 醞釀中(量縮) / 醞釀中。"""
    stage = row.get("stage")
    if stage == "breakout":
        return "剛突破"
    if stage == "forming":
        return "醞釀中(量縮)" if row["vol_dry"] else "醞釀中"
    if row["vol_dry"]:
        return "待突破(量縮)"
    return "待突破"


def _persist_watchlist(conn, scan_date, rows):
    """寫入 vcp_watchlist 表（upsert）。表不存在或寫入失敗時不影響原本印出。"""
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('vcp_watchlist')")
            if cur.fetchone()[0] is None:
                print("[watchlist] vcp_watchlist 表不存在，略過寫入（請先套用 15_vcp_watchlist.sql）",
                      file=sys.stderr)
                return
            payload = [{
                "scan_date": scan_date,
                "symbol": r["symbol"],
                "name": r["name"] or None,
                "close": r["close"],
                "pivot": r["pivot"],
                "distance_pct": r["dist"],
                "contraction_count": r["nc"],
                "last_drawdown_pct": r["last_dd"],
                "score": r["score"],
                "status": _watchlist_status(r),
                "vol_dry": bool(r["vol_dry"]),
            } for r in rows]
            if payload:
                cur.executemany(_WATCHLIST_UPSERT_SQL, payload)
        conn.commit()
        print(f"[watchlist] 已寫入 vcp_watchlist：{scan_date} {len(rows)} 檔")
    except Exception as exc:
        conn.rollback()
        print(f"[watchlist] 寫入 vcp_watchlist 失敗（不影響掃描輸出）：{exc}", file=sys.stderr)


def cmd_watchlist(target_date=None):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT max(ts) FROM daily_prices")
            db_max = pd.Timestamp(cur.fetchone()[0])
            max_ts = pd.Timestamp(target_date) if target_date else db_max
            cur.execute("SELECT symbol, name FROM symbols WHERE market='TW'")
            names = {s: (n or "") for s, n in cur.fetchall()}
        rows = []
        for sym in load_symbols(conn):
            df = load_prices(conn, sym)
            if len(df) < 201:
                continue
            mask = (df["ts"] == max_ts).to_numpy()
            if not mask.any():        # 該檔當日無資料（殭屍/停牌/非交易日）→ 跳過
                continue
            d = int(np.where(mask)[0][0])
            if d < 200:
                continue
            ts, o, h, l, c, v = to_arrays(df)
            res = detect_vcp_at(ts, o, h, l, c, v, d)
            # 三階段：剛突破/待突破（完整候選貼近樞紐）+ 醞釀中（收縮成形、尚未到樞紐 → 預測快形成）
            stage = _vcp_stage(res)
            if stage is None:
                continue
            rows.append({
                "symbol": sym, "name": names.get(sym, ""),
                "close": round(res.close, 2), "pivot": round(res.pivot_price, 2),
                "dist": round(res.distance_to_pivot * 100, 2),
                "nc": res.contraction_count,
                "last_dd": round(res.last_drawdown * 100, 2),
                "vol_dry": res.volume_dry_up, "breakout": res.breakout,
                "score": round(res.score, 1),
                "stage": stage,
            })
        # 末段（breakout/near）優先於早期（forming），同組內依分數高、距樞紐近排序
        _stage_rank = {"breakout": 0, "near": 1, "forming": 2}
        rows.sort(key=lambda r: (_stage_rank.get(r["stage"], 9), -r["score"], r["dist"]))
        rows = rows[:50]

        # 寫入 vcp_watchlist 表（展示快照）：先刪該 scan_date 舊列，再 upsert。
        _persist_watchlist(conn, max_ts.date(), rows)

        print(f"[watchlist] {max_ts.date()} VCP 候選監控清單：{len(rows)} 檔（接近突破、該盯的）")
        print(f"{'symbol':<10}{'close':>9}{'pivot':>9}{'dist%':>8}{'nc':>4}{'lastDD%':>9}{'score':>7}  status  name")
        for r in rows:
            st = "BREAKOUT" if r["breakout"] else ("dry-near" if r["vol_dry"] else "near")
            print(f"{r['symbol']:<10}{r['close']:>9}{r['pivot']:>9}{r['dist']:>8}{r['nc']:>4}"
                  f"{r['last_dd']:>9}{r['score']:>7}  {st:<9}{r['name']}")
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
def main():
    valid = ("scan", "bootstrap", "backtest", "watchlist")
    if len(sys.argv) < 2 or sys.argv[1] not in valid:
        print("用法: python main.py [scan|bootstrap|backtest|watchlist [YYYY-MM-DD]]", file=sys.stderr)
        sys.exit(2)
    if sys.argv[1] == "watchlist":
        cmd_watchlist(sys.argv[2] if len(sys.argv) > 2 else None)
    elif sys.argv[1] == "scan":
        cmd_scan()
    elif sys.argv[1] == "bootstrap":
        cmd_bootstrap()
    else:
        cmd_backtest()


if __name__ == "__main__":
    main()
