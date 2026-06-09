#!/bin/sh
# 每日掃描（由 scheduler 容器的 crond 每天 15:00 TPE 觸發）
# 透過掛載的 docker socket 觸發各容器，連既有 stock_default network 與 stock-timescaledb。
DBURL="postgresql://stock_app:${STOCK_APP_PASSWORD}@stock-timescaledb:5432/stockdb"
echo "$(date '+%Y-%m-%d %H:%M:%S') ===== 每日掃描開始 ====="

# 1. 抓現有 universe 最新行情（近 1 年增量，upsert 覆蓋最新交易日）
TICKERS=$(docker exec stock-timescaledb psql -U stock_admin -d stockdb -tAc \
    "SELECT string_agg(symbol,' ' ORDER BY symbol) FROM symbols")
echo "抓行情 ..."
# shellcheck disable=SC2086
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-loader $TICKERS --years 1 2>&1 | tail -1

# 2. 還原權值（更新除權息係數）
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-loader --adjust 2>&1 | tail -1

# 3. VCP 監控清單（寫今日 vcp_watchlist → 儀表板/MCP 自動顯示）
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-vcp watchlist 2>&1 | tail -1

# 4. 5-10-20 掃描候選 + 5. 評分到期預測
docker exec stock-timescaledb psql -U stock_admin -d stockdb \
    -c "SELECT scan_strategy_candidates();" -c "SELECT evaluate_due_predictions();"

echo "$(date '+%Y-%m-%d %H:%M:%S') ===== 每日掃描完成 ====="
