"""
chiploader/main.py — 台股籌碼 ingestion
用法:
  docker compose run --rm chiploader 2330.TW 2317.TW
  docker compose run --rm chiploader --universe      # 抓 symbols 表所有 market='TW'
"""

import os
import sys
import time
import argparse
import requests
import psycopg2
from datetime import datetime, timedelta

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = os.getenv("FINMIND_TOKEN", "")
DATABASE_URL = os.environ["DATABASE_URL"]

# 抓近 ~2 年
START_DATE = (datetime.today() - timedelta(days=730)).strftime("%Y-%m-%d")


def get_db():
    return psycopg2.connect(DATABASE_URL)


def get_tw_universe(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM symbols WHERE market = 'TW'")
        return [row[0] for row in cur.fetchall()]


def finmind_fetch(dataset: str, stock_id: str, retries: int = 3) -> list[dict]:
    """Fetch FinMind dataset for a single stock_id, return list of row dicts."""
    params = {
        "dataset": dataset,
        "data_id": stock_id,
        "start_date": START_DATE,
        "token": FINMIND_TOKEN,
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(FINMIND_URL, params=params, timeout=60)
            body = r.json()
            if body.get("status") != 200:
                print(f"  [WARN] FinMind {dataset} {stock_id}: status={body.get('status')} msg={body.get('msg')}")
                return []
            return body.get("data", [])
        except Exception as e:
            print(f"  [WARN] attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return []


def ingest_institutional(conn, symbol: str, stock_id: str):
    """
    TaiwanStockInstitutionalInvestorsBuySell
    Fields: date, stock_id, name, buy, sell
    name values: Foreign_Investor, Investment_Trust,
                 Dealer_self, Dealer_Hedging, Foreign_Dealer_Self
    """
    rows = finmind_fetch("TaiwanStockInstitutionalInvestorsBuySell", stock_id)
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


def ingest_margin(conn, symbol: str, stock_id: str):
    """
    TaiwanStockMarginPurchaseShortSale
    Key fields:
      MarginPurchaseTodayBalance, MarginPurchaseYesterdayBalance
      ShortSaleTodayBalance,      ShortSaleYesterdayBalance
    """
    rows = finmind_fetch("TaiwanStockMarginPurchaseShortSale", stock_id)
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


def process_symbol(conn, symbol: str):
    # 非台股 → 跳過
    if not (symbol.endswith(".TW") or symbol.endswith(".TWO")):
        print(f"[SKIP] {symbol} is not a TW/TWO symbol — skipping")
        return

    # 取純數字 stock_id
    stock_id = symbol.split(".")[0]
    print(f"[INFO] Processing {symbol} (stock_id={stock_id}) ...")

    n_inst   = ingest_institutional(conn, symbol, stock_id)
    n_margin = ingest_margin(conn, symbol, stock_id)
    print(f"  chip_institutional: {n_inst} rows upserted")
    print(f"  chip_margin:        {n_margin} rows upserted")


def main():
    parser = argparse.ArgumentParser(description="台股籌碼 ingestion")
    parser.add_argument("symbols", nargs="*", help="Symbol(s) e.g. 2330.TW 2317.TW")
    parser.add_argument("--universe", action="store_true",
                        help="抓 symbols 表所有 market='TW' 標的")
    args = parser.parse_args()

    conn = get_db()

    if args.universe:
        symbols = get_tw_universe(conn)
        print(f"[INFO] Universe mode: {len(symbols)} TW symbols")
    elif args.symbols:
        symbols = args.symbols
    else:
        parser.print_help()
        sys.exit(1)

    for sym in symbols:
        process_symbol(conn, sym)

    conn.close()
    print("[DONE]")


if __name__ == "__main__":
    main()
