"""
chiploader/main.py — 台股籌碼 ingestion（三大法人 + 融資券）
用法:
  docker compose run --rm chiploader 2330.TW 2317.TW
  docker compose run --rm chiploader --universe              # FinMind 依個股抓（三大法人+融資券），預設 10Y
  docker compose run --rm chiploader --universe --years 1    # 每日增量（只抓近 1 年，request 數同、payload 較小）

  融資融券/三大法人改走 TWSE（免 token/額度，一次一日抓全上市市場）:
  docker compose run --rm chiploader --twse-margin           # 融資融券，最新交易日
  docker compose run --rm chiploader --twse-inst             # 三大法人，最新交易日
  docker compose run --rm chiploader --twse-inst --date 20260610
  docker compose run --rm chiploader --twse-inst --start 20160611 --end 20260611  # 區間回補
  共用旗標：--date 單日 / --days N 近 N 日 / --start..--end 區間回補 / --force 覆寫已有。
  註：TWSE（MI_MARGN/T86）僅含「上市」；上櫃(.TWO，目前 4 檔)需另接 TPEX，暫未涵蓋。
"""

import os
import sys
import time
import argparse
import requests
import psycopg2
from datetime import date, timedelta

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")
DATABASE_URL = os.environ["DATABASE_URL"]

# TWSE 信用交易（融資融券）每日全市場：MI_MARGN，selectType=STOCK 為個股明細
TWSE_MARGN_URL = "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
# TWSE 三大法人買賣超每日全市場：T86，selectType=ALLBUT0999 為全個股（單位：股數，與 FinMind 一致）
TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"

# 每檔之間的間隔（秒）：FinMind 免費額度以速率計，太密集會 402；對齊 loader 的 0.3s。
SYMBOL_SLEEP = 0.3
# TWSE 依日期請求的禮貌間隔（秒）：TWSE 反爬會回 HTTP 428 擋頁，太快會被封 IP；保守用 3s。
TWSE_SLEEP = 3.0


def start_date_for(years: float) -> str:
    return (date.today() - timedelta(days=int(years * 365.25))).isoformat()


def get_db():
    return psycopg2.connect(DATABASE_URL)


def get_tw_universe(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM symbols WHERE market = 'TW'")
        return [row[0] for row in cur.fetchall()]


def finmind_fetch(dataset: str, stock_id: str, start_date: str, retries: int = 4) -> list[dict]:
    """Fetch FinMind dataset for a single stock_id, return list of row dicts.

    status 402 = 「Requests reach the upper limit」（額度/速率上限）→ 視為可重試，
    指數退避後再試（backfill 抓全 universe 時很可能撞到）。其餘非 200 才當無資料。
    """
    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": start_date,
        "token": FINMIND_TOKEN,
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(FINMIND_URL, params=params, timeout=60)
            body = r.json()
            status = body.get("status")
            if status == 200:
                return body.get("data", [])
            if status == 402:
                wait = min(60, 5 * (2 ** (attempt - 1)))  # 5,10,20,40s（上限 60）
                print(f"  [RATE] FinMind {dataset} {stock_id}: 額度上限，{wait}s 後重試 ({attempt}/{retries})")
                if attempt < retries:
                    time.sleep(wait)
                    continue
                return []
            print(f"  [WARN] FinMind {dataset} {stock_id}: status={status} msg={body.get('msg')}")
            return []
        except Exception as e:
            print(f"  [WARN] attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return []


def ingest_institutional(conn, symbol: str, stock_id: str, start_date: str):
    """
    TaiwanStockInstitutionalInvestorsBuySell
    Fields: date, stock_id, name, buy, sell
    name values: Foreign_Investor, Investment_Trust,
                 Dealer_self, Dealer_Hedging, Foreign_Dealer_Self
    """
    rows = finmind_fetch("TaiwanStockInstitutionalInvestorsBuySell", stock_id, start_date)
    if not rows:
        print(f"  [INFO] No institutional data for {symbol}")
        return 0

    # Aggregate per date
    from collections import defaultdict
    by_date: dict[str, dict] = defaultdict(lambda: {
        "foreign_net": 0, "trust_net": 0, "dealer_net": 0
    })

    for row in rows:
        d = row["date"]
        name = row["name"]
        net = row["buy"] - row["sell"]
        if name == "Foreign_Investor":
            by_date[d]["foreign_net"] += net
        elif name == "Investment_Trust":
            by_date[d]["trust_net"] += net
        elif name in ("Dealer_self", "Dealer_Hedging", "Foreign_Dealer_Self"):
            by_date[d]["dealer_net"] += net

    upsert_sql = """
        INSERT INTO chip_institutional (symbol, ts, foreign_net, trust_net, dealer_net, total_net)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, ts) DO UPDATE SET
            foreign_net = EXCLUDED.foreign_net,
            trust_net   = EXCLUDED.trust_net,
            dealer_net  = EXCLUDED.dealer_net,
            total_net   = EXCLUDED.total_net
    """
    count = 0
    with conn.cursor() as cur:
        for date_str, nets in by_date.items():
            foreign_net = nets["foreign_net"]
            trust_net   = nets["trust_net"]
            dealer_net  = nets["dealer_net"]
            total_net   = foreign_net + trust_net + dealer_net
            cur.execute(upsert_sql, (
                symbol, date_str,
                foreign_net, trust_net, dealer_net, total_net
            ))
            count += 1
    conn.commit()
    return count


def ingest_margin(conn, symbol: str, stock_id: str, start_date: str):
    """
    TaiwanStockMarginPurchaseShortSale
    Key fields:
      MarginPurchaseTodayBalance, MarginPurchaseYesterdayBalance
      ShortSaleTodayBalance,      ShortSaleYesterdayBalance
    註：創新板/部分 KY 股不得融資融券，FinMind 回空 → 該檔 chip_margin 無資料屬正常。
    """
    rows = finmind_fetch("TaiwanStockMarginPurchaseShortSale", stock_id, start_date)
    if not rows:
        print(f"  [INFO] No margin data for {symbol}")
        return 0

    upsert_sql = """
        INSERT INTO chip_margin (symbol, ts, margin_balance, margin_change, short_balance, short_change)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, ts) DO UPDATE SET
            margin_balance = EXCLUDED.margin_balance,
            margin_change  = EXCLUDED.margin_change,
            short_balance  = EXCLUDED.short_balance,
            short_change   = EXCLUDED.short_change
    """
    count = 0
    with conn.cursor() as cur:
        for row in rows:
            margin_balance = row["MarginPurchaseTodayBalance"]
            margin_change  = row["MarginPurchaseTodayBalance"] - row["MarginPurchaseYesterdayBalance"]
            short_balance  = row["ShortSaleTodayBalance"]
            short_change   = row["ShortSaleTodayBalance"] - row["ShortSaleYesterdayBalance"]
            cur.execute(upsert_sql, (
                symbol, row["date"],
                margin_balance, margin_change,
                short_balance, short_change
            ))
            count += 1
    conn.commit()
    return count


# ── 融資融券：TWSE MI_MARGN（依日期，一次抓全上市市場）──────────────────────
def _to_int(x) -> int:
    """TWSE 數字字串（含千分位逗號）→ int；空白/破折號 → 0。"""
    s = str(x).replace(",", "").strip()
    if s in ("", "-", "--"):
        return 0
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return 0


TWSE_HDRS = {"User-Agent": "Mozilla/5.0"}


def twse_fetch_json(url, date_params, referer, retries: int = 5):
    """通用 TWSE RWD GET。回傳 tuple:
       ("ok", body)    — stat=OK，body 為解析後 JSON
       ("empty", None) — 該日無交易（假日/未公布）
       ("fail", None)  — HTTP 428 擋頁 / 連線 / JSON / 異常 stat 重試用盡
    一律帶遞增 `_` cache-buster（毫秒時間戳）：避免打到 CDN 快取的舊錯誤回應
    （實測 20160606 不帶 `_` 會拿到被快取的「查詢日期小於90年」錯誤，帶了才回正常資料）。
    """
    headers = {**TWSE_HDRS, "Referer": referer}
    d = date_params.get("date")
    for attempt in range(1, retries + 1):
        params = {**date_params, "response": "json", "_": str(int(time.time() * 1000))}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=60)
            if r.status_code != 200:  # TWSE 反爬常回 428 擋頁 → 長退避（封鎖通常數分鐘）
                wait = min(300, 60 * attempt)
                print(f"  [HTTP {r.status_code}] {d}: 疑似限流，{wait}s 後重試 ({attempt}/{retries})")
                if attempt < retries:
                    time.sleep(wait); continue
                return ("fail", None)
            body = r.json()
        except Exception as e:
            wait = min(300, 60 * attempt)
            print(f"  [WARN] {d} attempt {attempt}/{retries}: {type(e).__name__} → {wait}s 後重試")
            if attempt < retries:
                time.sleep(wait); continue
            return ("fail", None)

        stat = body.get("stat") or ""
        if stat == "OK":
            return ("ok", body)
        if "沒有符合條件的資料" in stat or "無符合條件" in stat:
            return ("empty", None)  # 正常空日（假日/未公布）
        # 異常 stat（如「查詢日期小於90年1月1日」多為快取舊錯誤）→ 換新 `_` 重試，仍異常才算失敗
        print(f"  [STAT] {d}: {stat} → 重試")
        if attempt < retries:
            time.sleep(2); continue
        return ("fail", None)
    return ("fail", None)


def fetch_twse_margin(yyyymmdd: str):
    """TWSE MI_MARGN 單日全上市融資融券。
    回傳 {code:(margin_balance,margin_change,short_balance,short_change)}（張）；空日 {}；失敗 None。
    明細 16 欄：0代號 1名稱 | 融資 2買3賣4現償5前日餘額6今日餘額7限額 |
              融券 8賣9買10現償11前日餘額12今日餘額13限額 | 14資券互抵 15備註。
    """
    kind, body = twse_fetch_json(TWSE_MARGN_URL, {"date": yyyymmdd, "selectType": "STOCK"},
                                 "https://www.twse.com.tw/zh/trading/margin/mi-margn.html")
    if kind == "fail":
        return None
    if kind == "empty":
        return {}
    out = {}
    for t in body.get("tables", []):
        data = t.get("data") or []
        if not data or len(data[0]) < 15:
            continue  # 跳過非個股明細表
        for row in data:
            code = str(row[0]).strip()
            if not (code.isdigit() and len(code) == 4):
                continue  # 跳過合計/小計列
            mbal, mprev = _to_int(row[6]), _to_int(row[5])
            sbal, sprev = _to_int(row[12]), _to_int(row[11])
            out[code] = (mbal, mbal - mprev, sbal, sbal - sprev)
    return out


def _find_col(fields, *needles, exclude=()) -> int:
    """回傳第一個「含全部 needles 且不含任何 exclude」的欄位索引；找不到回 -1。"""
    for i, f in enumerate(fields):
        if all(n in f for n in needles) and not any(e in f for e in exclude):
            return i
    return -1


def fetch_twse_inst(yyyymmdd: str):
    """TWSE T86 單日全上市三大法人買賣超。
    回傳 {code:(foreign_net,trust_net,dealer_net,total_net)}（股數，與 FinMind 一致）；空日 {}；失敗 None。
    用欄位名稱定位（兼容歷年格式變動）：
      foreign = 外陸資買賣超(不含外資自營商)｜trust = 投信買賣超｜total = 三大法人買賣超；
      dealer  = total - foreign - trust（吸收自營商+外資自營商，與既有 FinMind 資料的桶分一致）。
    """
    kind, body = twse_fetch_json(TWSE_T86_URL, {"date": yyyymmdd, "selectType": "ALLBUT0999"},
                                 "https://www.twse.com.tw/zh/trading/foreign/t86.html")
    if kind == "fail":
        return None
    if kind == "empty":
        return {}
    fields = body.get("fields") or []
    data = body.get("data") or []
    if not (fields and data):  # 少數時期可能改用 tables 包裝
        for t in body.get("tables", []):
            if t.get("fields") and t.get("data"):
                fields, data = t["fields"], t["data"]
                break
    fi = _find_col(fields, "買賣超", "不含外資自營商")          # 新格式：外陸資買賣超(不含外資自營商)
    if fi < 0:
        fi = _find_col(fields, "外資買賣超", exclude=("自營商",))  # 舊格式：外資買賣超股數
    ti = _find_col(fields, "投信買賣超")
    toti = _find_col(fields, "三大法人買賣超")
    if fi < 0 or ti < 0 or toti < 0:  # 欄位定位失敗 → 不寫殘缺資料，記為失敗顯式揭露
        print(f"  [WARN] T86 {yyyymmdd} 欄位定位失敗 fi={fi} ti={ti} tot={toti}")
        return None
    need = max(fi, ti, toti)
    out = {}
    for row in data:
        if len(row) <= need:   # 合計列/格式較舊的短列 → 跳過，避免 IndexError
            continue
        code = str(row[0]).strip()
        if not (code.isdigit() and len(code) == 4):
            continue
        fnet, tnet, tot = _to_int(row[fi]), _to_int(row[ti]), _to_int(row[toti])
        out[code] = (fnet, tnet, tot - fnet - tnet, tot)
    return out


def get_tw_listed_codes(conn) -> set:
    """universe 中的上市(.TW)股票代號集合（用於過濾 TWSE 全市場明細，避免寫入非 universe 標的）。"""
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM symbols WHERE market='TW' AND symbol LIKE '%.TW'")
        return {r[0].split(".")[0] for r in cur.fetchall()}


MIN_EXISTING = 50  # 某交易日某表已有 >= 此筆數 → 視為已回補，跳過（可續跑）


def existing_count(conn, table: str, ts: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table} WHERE ts = %s", (ts,))  # table 為內部常數，非外部輸入
        return cur.fetchone()[0]


def ingest_margin_twse(conn, yyyymmdd: str, codes: set) -> int:
    """抓單日 TWSE 融資融券 upsert chip_margin（只寫 universe 上市標的）。寫入筆數 / 空日 0 / 失敗 -1。"""
    data = fetch_twse_margin(yyyymmdd)
    if data is None:
        return -1
    if not data:
        return 0
    ts = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    sql = """INSERT INTO chip_margin (symbol, ts, margin_balance, margin_change, short_balance, short_change)
             VALUES (%s, %s, %s, %s, %s, %s)
             ON CONFLICT (symbol, ts) DO UPDATE SET
               margin_balance=EXCLUDED.margin_balance, margin_change=EXCLUDED.margin_change,
               short_balance=EXCLUDED.short_balance, short_change=EXCLUDED.short_change"""
    count = 0
    with conn.cursor() as cur:
        for code, (mbal, mchg, sbal, schg) in data.items():
            if code not in codes:
                continue
            cur.execute(sql, (code + ".TW", ts, mbal, mchg, sbal, schg))
            count += 1
    conn.commit()
    return count


def ingest_inst_twse(conn, yyyymmdd: str, codes: set) -> int:
    """抓單日 TWSE T86 三大法人 upsert chip_institutional（只寫 universe 上市標的）。寫入筆數 / 空日 0 / 失敗 -1。"""
    data = fetch_twse_inst(yyyymmdd)
    if data is None:
        return -1
    if not data:
        return 0
    ts = f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    sql = """INSERT INTO chip_institutional (symbol, ts, foreign_net, trust_net, dealer_net, total_net)
             VALUES (%s, %s, %s, %s, %s, %s)
             ON CONFLICT (symbol, ts) DO UPDATE SET
               foreign_net=EXCLUDED.foreign_net, trust_net=EXCLUDED.trust_net,
               dealer_net=EXCLUDED.dealer_net, total_net=EXCLUDED.total_net"""
    count = 0
    with conn.cursor() as cur:
        for code, (fnet, tnet, dnet, tot) in data.items():
            if code not in codes:
                continue
            cur.execute(sql, (code + ".TW", ts, fnet, tnet, dnet, tot))
            count += 1
    conn.commit()
    return count


def backfill_twse(conn, codes, start_yyyymmdd, end_yyyymmdd, force, ingest_fn, table, label):
    """依日期區間回補（通用於 margin / inst）：跳週末、（預設）跳已有資料日、禮貌間隔、統計失敗日。"""
    d0 = date(int(start_yyyymmdd[:4]), int(start_yyyymmdd[4:6]), int(start_yyyymmdd[6:]))
    d1 = date(int(end_yyyymmdd[:4]), int(end_yyyymmdd[4:6]), int(end_yyyymmdd[6:]))
    total_days = (d1 - d0).days + 1
    print(f"[INFO] TWSE 回補 {label} {start_yyyymmdd}~{end_yyyymmdd}（{total_days} 日曆日，跳週末/已有資料={not force}）")

    written = skipped = holiday = 0
    failed = []
    d = d0
    while d <= d1:
        if d.weekday() >= 5:        # 5,6 = 週六日，無交易
            d += timedelta(days=1)
            continue
        ts = d.isoformat()
        if not force and existing_count(conn, table, ts) >= MIN_EXISTING:
            skipped += 1
            d += timedelta(days=1)
            continue
        n = ingest_fn(conn, d.strftime("%Y%m%d"), codes)
        if n == -1:
            failed.append(ts)
            print(f"  [FAIL] {ts} 抓取失敗（已重試）")
        elif n == 0:
            holiday += 1            # 國定假日等非交易日
        else:
            written += 1
            if written % 50 == 0:
                print(f"  ... {ts}: 已寫 {written} 個交易日")
        time.sleep(TWSE_SLEEP)
        d += timedelta(days=1)

    print(f"[DONE] {label} 回補：寫入 {written} / 跳過已有 {skipped} / 假日 {holiday} / 失敗 {len(failed)}")
    if failed:
        print(f"  失敗日（可重跑相同指令續補）：{', '.join(failed[:30])}{' ...' if len(failed) > 30 else ''}")


def run_twse(conn, kind, single_date, days, start, end, force):
    """TWSE 模式（kind: 'margin' | 'inst'）：
      --start[/--end] → 區間回補；--date → 單日；--days → 近 N 日曆日；皆無 → 最新交易日。"""
    codes = get_tw_listed_codes(conn)
    if kind == "margin":
        ingest_fn, table, label = ingest_margin_twse, "chip_margin", "融資融券"
    else:
        ingest_fn, table, label = ingest_inst_twse, "chip_institutional", "三大法人"
    print(f"[INFO] TWSE {label}；universe 上市標的 {len(codes)} 檔")

    if start:
        backfill_twse(conn, codes, start, end or date.today().strftime("%Y%m%d"),
                      force, ingest_fn, table, label)
        return

    if single_date:
        dates = [single_date]
    elif days:
        dates = [(date.today() - timedelta(days=i)).strftime("%Y%m%d") for i in range(days)]
    else:
        for i in range(8):  # 最新交易日：今天往前找最近一個有資料的交易日
            d = (date.today() - timedelta(days=i)).strftime("%Y%m%d")
            n = ingest_fn(conn, d, codes)
            if n > 0:
                print(f"  {d}: {n} 檔寫入（最新交易日）")
                return
            print(f"  {d}: 無資料（非交易日/未公布），往前一日 ...")
            time.sleep(TWSE_SLEEP)
        print("  [WARN] 近 8 日皆無資料")
        return

    total = 0
    for d in dates:
        n = ingest_fn(conn, d, codes)
        total += max(n, 0)
        if n > 0:
            print(f"  {d}: {n} 檔")
        time.sleep(TWSE_SLEEP)
    print(f"[DONE] {label} 寫入合計 {total} 列 / {len(dates)} 個日期")


def process_symbol(conn, symbol: str, start_date: str):
    # 非台股 → 跳過
    if not (symbol.endswith(".TW") or symbol.endswith(".TWO")):
        print(f"[SKIP] {symbol} is not a TW/TWO symbol — skipping")
        return

    # 取純數字 stock_id
    stock_id = symbol.split(".")[0]
    print(f"[INFO] Processing {symbol} (stock_id={stock_id}) ...")

    n_inst   = ingest_institutional(conn, symbol, stock_id, start_date)
    n_margin = ingest_margin(conn, symbol, stock_id, start_date)
    print(f"  chip_institutional: {n_inst} rows upserted")
    print(f"  chip_margin:        {n_margin} rows upserted")


def main():
    parser = argparse.ArgumentParser(description="台股籌碼 ingestion")
    parser.add_argument("symbols", nargs="*", help="Symbol(s) e.g. 2330.TW 2317.TW")
    parser.add_argument("--universe", action="store_true",
                        help="抓 symbols 表所有 market='TW' 標的")
    parser.add_argument("--years", type=float, default=10,
                        help="回溯年數（預設 10，對齊行情；每日增量用 --years 1）")
    parser.add_argument("--twse-margin", action="store_true",
                        help="融資融券改走 TWSE MI_MARGN（依日期、免 token/額度，僅上市）")
    parser.add_argument("--twse-inst", action="store_true",
                        help="三大法人改走 TWSE T86（依日期、免 token/額度，僅上市）")
    parser.add_argument("--date", help="TWSE 模式：指定單日 YYYYMMDD")
    parser.add_argument("--days", type=int, help="TWSE 模式：回補近 N 個日曆日")
    parser.add_argument("--start", help="TWSE 回補：起始日 YYYYMMDD（區間回補）")
    parser.add_argument("--end", help="TWSE 回補：結束日 YYYYMMDD（預設今天）")
    parser.add_argument("--force", action="store_true",
                        help="TWSE 回補：不跳過已有資料的日期（重新覆寫）")
    args = parser.parse_args()

    conn = get_db()

    # ── TWSE 依日期模式（融資融券 / 三大法人，與 FinMind 依個股抓互斥）─────────
    if args.twse_margin or args.twse_inst:
        kind = "inst" if args.twse_inst else "margin"
        run_twse(conn, kind, args.date, args.days, args.start, args.end, args.force)
        conn.close()
        print("[DONE]")
        return

    start_date = start_date_for(args.years)
    print(f"[INFO] start_date={start_date} (years={args.years})")

    if args.universe:
        symbols = get_tw_universe(conn)
        print(f"[INFO] Universe mode: {len(symbols)} TW symbols")
    elif args.symbols:
        symbols = args.symbols
    else:
        parser.print_help()
        sys.exit(1)

    for i, sym in enumerate(symbols, 1):
        process_symbol(conn, sym, start_date)
        if i < len(symbols):
            time.sleep(SYMBOL_SLEEP)  # 速率節流，避免整批 universe 撞 FinMind 402

    conn.close()
    print("[DONE]")


if __name__ == "__main__":
    main()
