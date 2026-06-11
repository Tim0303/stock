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

# 2b. 籌碼面增量：走 TWSE 依日期端點（免 token/額度，一次一日抓全上市）。
#     用 --days 3 抓近 3 個日曆日：T86/MI_MARGN 約收盤後才公布，這樣即使當日尚未公布或前一日漏跑也能補齊。
#     註：僅涵蓋上市(.TW)；上櫃(.TWO，4 檔)未涵蓋（需 TPEX）。
echo "抓三大法人 (TWSE T86) ..."
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-chiploader --twse-inst   --days 3 2>&1 | tail -1
echo "抓融資融券 (TWSE MI_MARGN) ..."
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-chiploader --twse-margin --days 3 2>&1 | tail -1

# 3. VCP 監控清單（寫今日 vcp_watchlist → 儀表板/MCP 自動顯示）
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-vcp watchlist 2>&1 | tail -1

# 4. 記錄當日推薦為「預測」→ analyses（到期由 evaluate 評分，走學習迴路）
echo "記錄當日推薦 (analyses) ..."
#   4a. VCP 突破訊號（Python）
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-vcp scan 2>&1 | tail -1
#   4b. ML：每週六用累積新資料重訓（bracket 標籤 + OOS 驗證）；每日 predict 載入持久化模型(ml_models volume)。
#       門檻 0.60 高選擇性：弱市常 0 買進屬正常（抽手）。
if [ "$(date +%u)" = "6" ]; then
  echo "ML 週重訓 ..."
  docker run --rm --network stock_default -v stock_ml_models:/app/models -e DATABASE_URL="$DBURL" stock-ml train 2>&1 | tail -3
fi
docker run --rm --network stock_default -v stock_ml_models:/app/models -e DATABASE_URL="$DBURL" stock-ml predict 2>&1 | tail -1
#   4c. 5-10-20 / 破支撐拉回 / 布林通道趨勢續抱 / 布林開口放量突破 買進訊號（DB function，live + 防重；box 已退役）
docker exec stock-timescaledb psql -U stock_admin -d stockdb \
    -c "SELECT record_strategy_signals();" \
    -c "SELECT record_spring_signals();" \
    -c "SELECT record_bb_trend_signals();" \
    -c "SELECT record_bb_breakout_signals();"

# 5. 每日推薦快照（所見即所記，含 VCP 醞釀中）→ daily_recommendations（供前向報酬驗證）
docker exec stock-timescaledb psql -U stock_admin -d stockdb \
    -c "SELECT snapshot_daily_recommendations();"

# 6. 5-10-20 掃描候選 + 7. 評分到期預測（bracket 全策略 + 趨勢續抱專屬評分）
docker exec stock-timescaledb psql -U stock_admin -d stockdb \
    -c "SELECT scan_strategy_candidates();" \
    -c "SELECT evaluate_due_predictions();" \
    -c "SELECT evaluate_bb_trend();" \
    -c "SELECT evaluate_bb_breakout();"

echo "$(date '+%Y-%m-%d %H:%M:%S') ===== 每日掃描完成 ====="
