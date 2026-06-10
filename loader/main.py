#!/usr/bin/env python3
"""loader — 行情 ingestion + 選股池(universe)建構

用法:
  python main.py 2330.TW AAPL              # 抓指定標的(台股 .TW/.TWO, 美股代號)
  python main.py --universe                # 建 universe(白名單+FinMind過濾+成交量補足) 並全抓
  python main.py --universe --target 55 --years 10

資料誠信: 台股中文名/產業別一律以 FinMind TaiwanStockInfo 查證後填入, 絕不臆測.
"""
import os
import sys
import time
import argparse
from datetime import date, timedelta

import requests
import pandas as pd
import yfinance as yf
import psycopg2
from psycopg2.extras import execute_values

DATABASE_URL = os.environ["DATABASE_URL"]
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN") or ""

# universe 指定白名單(優先納入, 凌駕產業過濾) — 見 plan 〇章 / 記憶 stock-universe-selection
WHITELIST = ["6658", "8028", "2317", "2489", "6213", "5434", "2330",
             "4977", "2327", "2458", "1815", "3163", "3363"]

# 排除金融+傳產(關鍵字子字串比對, 對保留的電子/生技/成長類不誤傷)
EXCLUDE_KEYWORDS = ["金融", "保險", "水泥", "食品", "塑膠", "紡織", "鋼鐵",
                    "橡膠", "造紙", "玻璃", "汽車", "航運", "觀光", "百貨",
                    "油電", "電器電纜", "電機機械", "化學", "建材", "貿易"]


def connect():
    return psycopg2.connect(DATABASE_URL)


# ── FinMind ────────────────────────────────────────────────────────────
def finmind_get(dataset, **extra):
    params = {"dataset": dataset}
    if FINMIND_TOKEN:
        params["token"] = FINMIND_TOKEN
    params.update(extra)
    r = requests.get(FINMIND_URL, params=params, timeout=90)
    r.raise_for_status()
    return r.json().get("data", [])


def load_tw_info():
    """TaiwanStockInfo -> dict[stock_id] = {name, industry, type}（僅 4 位數普通股）"""
    info = {}
    for row in finmind_get("TaiwanStockInfo"):
        sid = (row.get("stock_id") or "").strip()
        if not sid.isdigit() or len(sid) != 4 or sid.startswith("00"):
            continue  # 排除 ETF/權證/特別股等
        info[sid] = {
            "name": row.get("stock_name"),
            "industry": row.get("industry_category"),
            "type": (row.get("type") or "").lower(),
        }
    return info


def is_excluded_industry(ind):
    if not ind:
        return True  # 無產業資訊 → 保守排除(白名單另外強制納入)
    return any(k in ind for k in EXCLUDE_KEYWORDS)


def tw_ticker(sid, type_):
    """FinMind type → yfinance 後綴: 上櫃(tpex/otc) .TWO, 其餘上市 .TW"""
    return sid + (".TWO" if ("tpex" in type_ or "otc" in type_) else ".TW")


# ── 行情抓取 ────────────────────────────────────────────────────────────
def _num(x):
    return None if pd.isna(x) else float(x)


# ── 台股歷史日線：FinMind TaiwanStockPrice（單檔 data_id 一次抓全範圍）──
def start_date_for(years):
    return (date.today() - timedelta(days=int(years * 365.25))).isoformat()


def fetch_prices_finmind(sid, years):
    """台股日線走 FinMind TaiwanStockPrice。
    註：close=0 代表當日「暫停交易」（停牌），由 upsert_prices 的 close>0 過濾排除。"""
    data = finmind_get("TaiwanStockPrice", data_id=sid, start_date=start_date_for(years))
    if not data:
        return None
    df = pd.DataFrame(data)
    need = {"date", "open", "max", "min", "close", "Trading_Volume"}
    if not need.issubset(df.columns):
        return None
    df = df.rename(columns={"date": "Date", "open": "Open", "max": "High",
                            "min": "Low", "close": "Close", "Trading_Volume": "Volume"})
    df["Date"] = pd.to_datetime(df["Date"])
    df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    return df if len(df) else None


def fetch_prices_yf(yf_ticker, years):
    """美股走 yfinance（台股不用此路徑）"""
    df = yf.download(yf_ticker, period=f"{years}y", interval="1d",
                     auto_adjust=False, progress=False, threads=False)
    if df is None or len(df) == 0:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    keep = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].dropna(subset=["Close"])
    return df if len(df) else None


# ── upsert ─────────────────────────────────────────────────────────────
def upsert_symbol(cur, symbol, name, market, industry, is_wl):
    cur.execute("""
        INSERT INTO symbols (symbol, name, market, industry_category, is_whitelist)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            name = COALESCE(EXCLUDED.name, symbols.name),
            market = EXCLUDED.market,
            industry_category = COALESCE(EXCLUDED.industry_category, symbols.industry_category),
            is_whitelist = symbols.is_whitelist OR EXCLUDED.is_whitelist
    """, (symbol, name, market, industry, is_wl))


def _pos(x):
    v = _num(x)
    return v if (v is not None and v > 0) else None


def upsert_prices(cur, symbol, df):
    # 排除停牌日：close=0 代表當日「暫停交易」（無有效收盤），不應進均線/回測；
    # open/high/low <= 0 轉 NULL。
    rows = [(symbol, r.Date.date() if hasattr(r.Date, "date") else r.Date,
             _pos(r.Open), _pos(r.High), _pos(r.Low), _num(r.Close),
             None if pd.isna(r.Volume) else int(r.Volume))
            for r in df.itertuples(index=False)
            if not pd.isna(r.Close) and float(r.Close) > 0]
    if not rows:
        return 0
    execute_values(cur, """
        INSERT INTO daily_prices (symbol, ts, open, high, low, close, volume)
        VALUES %s
        ON CONFLICT (symbol, ts) DO UPDATE SET
            open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
            close = EXCLUDED.close, volume = EXCLUDED.volume
    """, rows)
    return len(rows)


def ingest(cur, yf_ticker, tw_info, years, is_wl=False):
    if yf_ticker.endswith((".TW", ".TWO")):
        sid = yf_ticker.split(".")[0]
        meta = tw_info.get(sid, {})
        name, industry, market = meta.get("name"), meta.get("industry"), "TW"
        df = fetch_prices_finmind(sid, years)       # 台股上市/上櫃 → FinMind
    else:
        name, industry, market = None, None, "US"
        df = fetch_prices_yf(yf_ticker, years)
    if df is None:
        print(f"  [skip] {yf_ticker}: 無資料")
        return 0
    upsert_symbol(cur, yf_ticker, name, market, industry, is_wl)
    return upsert_prices(cur, yf_ticker, df)


# ── universe 建構 ──────────────────────────────────────────────────────
def fetch_twse_trade_value():
    """TWSE OpenAPI 全市場當日成交金額(一次請求, 免 token, 僅上市) → dict[code]=TradeValue。
    FinMind 不支援全市場查詢(必須 data_id), 故流動性排序改用證交所開放資料。"""
    try:
        r = requests.get("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", timeout=60)
        r.raise_for_status()
        out = {}
        for row in r.json():
            code = row.get("Code")
            tv = (row.get("TradeValue") or "").replace(",", "")
            if code and tv:
                try:
                    out[code] = float(tv)
                except ValueError:
                    pass
        return out
    except Exception as e:
        print(f"  [warn] TWSE 成交值取得失敗, 改用原序: {e}")
        return {}


def rank_by_dollar_volume(sids):
    """用 TWSE 全市場當日成交金額排序(流動性前段優先)。
    上市股有資料→成交額降序;上櫃/無資料→排後面(白名單上櫃已強制納入)。"""
    tv = fetch_twse_trade_value()
    if not tv:
        return list(sids)
    ranked = sorted([s for s in sids if s in tv], key=lambda s: tv[s], reverse=True)
    rest = [s for s in sids if s not in tv]
    return ranked + rest


def build_universe(tw_info, target):
    """回傳 [(yf_ticker, sid, is_whitelist)]: 白名單優先 + 流動性補足到 target"""
    selected, seen = [], set()
    for sid in WHITELIST:
        m = tw_info.get(sid, {})
        selected.append((tw_ticker(sid, m.get("type", "")), sid, True))
        seen.add(sid)
    pool = [sid for sid, m in tw_info.items()
            if sid not in seen and not is_excluded_industry(m["industry"])]
    print(f"保留產業母體 {len(pool)} 檔, 依成交額排序補足到 {target} ...")
    for sid in rank_by_dollar_volume(pool):
        if len(selected) >= target:
            break
        selected.append((tw_ticker(sid, tw_info[sid].get("type", "")), sid, False))
    return selected


# ── 還原權值（後復權：除權息日 adj_factor 跳升，消除市價跳空）──────────────
def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _valid_exdate(s):
    return bool(s) and s not in ("", "0000-00-00", "1900-01-01")


def fetch_dividend_events(sid):
    """FinMind TaiwanStockDividend → [(ex_date_str, cash, stock_ratio)]。
    現金股利 → 純除息事件；股票股利 → 純除權事件（配股率 = 股票股利元 / 10，面額10）。"""
    events = []
    try:
        data = finmind_get("TaiwanStockDividend", data_id=sid, start_date="2010-01-01")
    except Exception:
        return events
    for row in data:
        cash = _f(row.get("CashEarningsDistribution")) + _f(row.get("CashStatutorySurplus"))
        stock = _f(row.get("StockEarningsDistribution")) + _f(row.get("StockStatutorySurplus"))
        ce, se = row.get("CashExDividendTradingDate"), row.get("StockExDividendTradingDate")
        if cash > 0 and _valid_exdate(ce):
            events.append((ce, cash, 0.0))
        if stock > 0 and _valid_exdate(se):
            events.append((se, 0.0, stock / 10.0))
    return events


def compute_adj_factor(cur, symbol):
    """以原始相鄰收盤算每次除權息補償係數，累乘後正規化（前復權）→ 寫 daily_prices.adj_factor。
    除息 ef = P_prev/(P_prev-cash)；除權 ef = 1+配股率；同日連乘。
    最後一筆係數 = 1.0（現價 = 實際成交價），歷史 < 1.0；報酬仍含息。"""
    cur.execute("SELECT ts, close FROM daily_prices WHERE symbol=%s AND close>0 ORDER BY ts", (symbol,))
    rows = cur.fetchall()
    if not rows:
        return 0
    dates = [r[0] for r in rows]
    closes = {r[0]: float(r[1]) for r in rows}
    ef_by_date = {}
    for ex, cash, sr in fetch_dividend_events(symbol.split(".")[0]):
        try:
            exd = date.fromisoformat(ex)
        except (ValueError, TypeError):
            continue
        prev = [d for d in dates if d < exd]
        if not prev:
            continue
        pprev = closes[prev[-1]]
        pref = (pprev - cash) / (1.0 + sr)
        if pref <= 0:
            continue
        ef_by_date[exd] = ef_by_date.get(exd, 1.0) * (pprev / pref)
    sorted_ex = sorted(ef_by_date)
    raw, cum, ei = [], 1.0, 0
    for d in dates:
        while ei < len(sorted_ex) and sorted_ex[ei] <= d:
            cum *= ef_by_date[sorted_ex[ei]]
            ei += 1
        raw.append((d, cum))
    # 前復權正規化：最近一筆 = 1.0，歷史往回縮放 → 現價 = 實際成交價、報酬仍含息。
    final = raw[-1][1] if raw else 1.0
    updates = [(round(c / final, 8), symbol, d) for (d, c) in raw]
    execute_values(cur,
        "UPDATE daily_prices AS dp SET adj_factor = v.f "
        "FROM (VALUES %s) AS v(f, sym, ts) WHERE dp.symbol = v.sym AND dp.ts = v.ts::date",
        updates)
    return len(updates)


def run_adjust():
    conn = connect()
    cur = conn.cursor()
    cur.execute("SELECT symbol FROM symbols WHERE market='TW' ORDER BY symbol")
    syms = [r[0] for r in cur.fetchall()]
    print(f"還原權值：{len(syms)} 檔台股 ...")
    for i, s in enumerate(syms, 1):
        try:
            n = compute_adj_factor(cur, s)
            conn.commit()
            print(f"[{i}/{len(syms)}] {s}: {n} 列")
        except Exception as e:
            conn.rollback()
            print(f"[{i}/{len(syms)}] {s}: 失敗 {e}")
        time.sleep(0.3)
    cur.close()
    conn.close()
    print("還原完成")


# ── main ───────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*")
    ap.add_argument("--universe", action="store_true")
    ap.add_argument("--target", type=int, default=55)
    ap.add_argument("--years", type=int, default=10)
    ap.add_argument("--adjust", action="store_true", help="計算還原權值係數（FinMind 除權息）")
    args = ap.parse_args()

    if args.adjust:
        run_adjust()
        return

    tw_info = {}
    if args.universe or any(s.endswith((".TW", ".TWO")) for s in args.symbols):
        print("抓 FinMind TaiwanStockInfo ...")
        try:
            tw_info = load_tw_info()
            print(f"  取得 {len(tw_info)} 檔台股基本資料")
        except Exception as e:
            print(f"  [warn] FinMind 取得失敗: {e}")

    if args.universe:
        targets = build_universe(tw_info, args.target)
    else:
        targets = [(s, s.split(".")[0] if s.endswith((".TW", ".TWO")) else None,
                    s.split(".")[0] in WHITELIST) for s in args.symbols]

    if not targets:
        print("沒有要抓的標的。用法見檔頭。")
        sys.exit(1)

    conn = connect()
    cur = conn.cursor()
    total = 0
    for i, (tk, _sid, is_wl) in enumerate(targets, 1):
        try:
            n = ingest(cur, tk, tw_info, args.years, is_wl)
            conn.commit()
            print(f"[{i}/{len(targets)}] {tk}: {n} 列")
            total += n
        except Exception as e:
            conn.rollback()
            print(f"[{i}/{len(targets)}] {tk}: 失敗 {e}")
        time.sleep(0.3)
    cur.close()
    conn.close()
    print(f"完成: {total} 列 / {len(targets)} 檔")


if __name__ == "__main__":
    main()
