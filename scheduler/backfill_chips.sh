#!/bin/bash
# 一次性：把三大法人/融資券歷史從 2 年回補到 10 年（與行情對齊）。
# 設計成可重入、對 FinMind 每小時額度有韌性：
#   每輪先探測額度（200 才開抓），抓完只針對「仍停在 ~2 年地板」且有更早行情的標的補抓，
#   直到無缺口或連續兩輪沒進展。可重複執行，upsert 不會重複資料。
set -u
cd "$(dirname "$0")/.." || exit 1

TOKEN=$(grep -i '^FINMIND_TOKEN=' .env | cut -d= -f2-)
APPPW=$(grep -i '^STOCK_APP_PASSWORD=' .env | cut -d= -f2-)
PGUSER=$(grep -i '^POSTGRES_USER=' .env | cut -d= -f2-)
PGDB=$(grep -i '^POSTGRES_DB=' .env | cut -d= -f2-)
DBURL="postgresql://stock_app:${APPPW}@stock-timescaledb:5432/${PGDB}"

psql_q() { docker exec stock-timescaledb psql -U "$PGUSER" -d "$PGDB" -tAc "$1" | tr -d '\r'; }

# 仍待回補：三大法人最早日期還停在 2 年地板(>2023-06-11)，且有更早行情(price_min < chip_min-30d)
GAP_SQL="WITH im AS (SELECT symbol, MIN(ts) cmin FROM chip_institutional GROUP BY symbol),
pm AS (SELECT symbol, MIN(ts) pmin FROM daily_prices GROUP BY symbol)
SELECT COALESCE(string_agg(im.symbol,' '),'') FROM im JOIN pm USING(symbol)
WHERE im.cmin > DATE '2023-06-11' AND pm.pmin < im.cmin - 30"

probe() {
  curl -s "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id=2330&start_date=2024-01-01&token=${TOKEN}" \
    | python -c "import sys,json;print(json.load(sys.stdin).get('status'))" 2>/dev/null
}

wait_quota() {
  for _ in $(seq 1 12); do            # 最多等 12×10 分鐘 = 2 小時
    s=$(probe)
    if [ "$s" = "200" ]; then return 0; fi
    echo "[$(date '+%H:%M:%S')] 額度未恢復 (status=$s)，10 分鐘後重探 ..."
    sleep 600
  done
  return 1
}

prev_gap=-1
for round in $(seq 1 10); do
  if [ "$round" = "1" ]; then
    TARGET="--universe"; label="全 universe"
  else
    GAP=$(psql_q "$GAP_SQL")
    GAP=$(echo "$GAP" | xargs)        # trim
    n=$(echo "$GAP" | wc -w)
    echo "[$(date '+%H:%M:%S')] 第 $round 輪：尚待回補 $n 檔"
    if [ "$n" = "0" ]; then echo "[DONE] 無缺口，回補完成"; break; fi
    if [ "$n" = "$prev_gap" ]; then echo "[STOP] 連續無進展（剩 $n 檔多為近年新上市/FinMind 無更早資料），停止"; break; fi
    prev_gap=$n
    TARGET="$GAP"; label="$n 檔缺口"
  fi

  echo "[$(date '+%H:%M:%S')] 探測 FinMind 額度 ..."
  if ! wait_quota; then echo "[ABORT] 等 2 小時額度仍未恢復，先停；稍後再跑本腳本即可續補"; exit 2; fi

  echo "[$(date '+%H:%M:%S')] 第 $round 輪開抓（$label，10Y）..."
  docker run --rm --network stock_default \
    -e DATABASE_URL="$DBURL" -e FINMIND_TOKEN="$TOKEN" \
    stock-chiploader $TARGET --years 10 2>&1 | grep -E '\[(INFO|RATE|DONE)\]|rows upserted' | tail -40
  sleep 30
done

echo "===== 回補後現況 ====="
psql_q "SELECT 'inst' t, COUNT(DISTINCT symbol) syms, MIN(ts) min_d, MAX(ts) max_d FROM chip_institutional
UNION ALL SELECT 'margin', COUNT(DISTINCT symbol), MIN(ts), MAX(ts) FROM chip_margin"
echo "[ALL DONE] $(date '+%Y-%m-%d %H:%M:%S')"
