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

# 4. 記錄當日推薦為「預測」→ analyses（到期由 evaluate 評分，走學習迴路）
echo "記錄當日推薦 (analyses) ..."
#   4a. VCP 突破訊號（Python）
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-vcp scan 2>&1 | tail -1
#   4b. ML 預測（Python；無模型則就地訓練）
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-ml predict 2>&1 | tail -1
#   4c. 5-10-20 / 破支撐拉回 / 布林通道趨勢續抱 買進訊號（DB function，live + 防重；box 已退役）
docker exec stock-timescaledb psql -U stock_admin -d stockdb \
    -c "SELECT record_strategy_signals();" \
    -c "SELECT record_spring_signals();" \
    -c "SELECT record_bb_trend_signals();"

# 5. 每日推薦快照（所見即所記，含 VCP 醞釀中）→ daily_recommendations（供前向報酬驗證）
docker exec stock-timescaledb psql -U stock_admin -d stockdb \
    -c "SELECT snapshot_daily_recommendations();"

# 6. 5-10-20 掃描候選 + 7. 評分到期預測（bracket 全策略 + 趨勢續抱專屬評分）
docker exec stock-timescaledb psql -U stock_admin -d stockdb \
    -c "SELECT scan_strategy_candidates();" \
    -c "SELECT evaluate_due_predictions();" \
    -c "SELECT evaluate_bb_trend();"

echo "$(date '+%Y-%m-%d %H:%M:%S') ===== 每日掃描完成 ====="
