#!/bin/sh
# 尾盤即時掃描（crond 每天 13:10 TPE，台股 13:30 收盤前）：
#   即時報價(MIS)→今日暫定收盤→VCP 以暫定盤刷新→凍結尾盤訊號快照→（有設 webhook 則）推 Discord。
# 純預覽：不寫 analyses；正式預測記錄仍由 15:00 daily_scan.sh 負責。
DBURL="postgresql://stock_app:${STOCK_APP_PASSWORD}@stock-timescaledb:5432/stockdb"
PSQL="docker exec stock-timescaledb psql -U stock_admin -d stockdb"
echo "$(date '+%Y-%m-%d %H:%M:%S') ===== 尾盤即時掃描開始 ====="

# 1. 即時報價 → 今日暫定 OHLCV（15:00 正式收盤會覆蓋）
echo "即時報價 (MIS) ..."
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-loader --intraday 2>&1 | tail -1

# 2. VCP 以暫定盤刷新監控清單（watchlist 子命令不寫 analyses）
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" stock-vcp watchlist 2>&1 | tail -1

# 3. 凍結尾盤訊號快照（5-10-20 / spring / bb-trend / vcp 剛突破）
N=$($PSQL -tAc "SELECT snapshot_eod_signals();" | tr -d '\r ')
echo "尾盤訊號快照：${N} 筆"

# 4. Discord 推播（未設 DISCORD_WEBHOOK_URL 則略過）。payload 由 Postgres 直接組合，確保合法 JSON。
if [ -n "$DISCORD_WEBHOOK_URL" ]; then
  PAYLOAD=$($PSQL -tAc "
    WITH s AS (
      SELECT skill,
             count(*) c,
             string_agg(symbol||' '||coalesce(name,'')||' ('||round(score)||')',
                        E'\n' ORDER BY score DESC NULLS LAST) lines
      FROM eod_intraday_signals
      WHERE scan_time = (SELECT max(scan_time) FROM eod_intraday_signals)
      GROUP BY skill
    )
    SELECT json_build_object('content',
      '**📈 今日尾盤訊號 '||to_char(now() AT TIME ZONE 'Asia/Taipei','MM/DD HH24:MI')||'**'||E'\n\n'||
      coalesce(string_agg('__'||skill||'__（'||c||' 檔）'||E'\n'||lines, E'\n\n' ORDER BY skill),
               '今日尾盤無買進訊號')
    )::text
    FROM s;")
  # s 無列時 string_agg 仍會回一筆（含 coalesce 預設字串）；保險再兜底
  if [ -z "$PAYLOAD" ]; then
    PAYLOAD='{"content":"**📈 今日尾盤訊號**\n今日尾盤無買進訊號"}'
  fi
  echo "推播 Discord ..."
  curl -s -m 20 -H "Content-Type: application/json" -d "$PAYLOAD" "$DISCORD_WEBHOOK_URL" >/dev/null \
    && echo "  Discord 已送出" || echo "  [warn] Discord 推播失敗"
else
  echo "（未設 DISCORD_WEBHOOK_URL，略過推播）"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') ===== 尾盤即時掃描完成 ====="
