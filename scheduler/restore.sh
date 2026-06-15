#!/bin/sh
# 在「另一台機器」還原資料庫（從 backup.sh 產生的 .dump）。
#
# 完整流程（新機器）：
#   1. git clone 專案、把舊機器的 .env 複製過來（密碼一致）。
#   2. docker compose up -d --build timescaledb   # 等 healthy（首次會跑 db/init 建 schema+roles）
#   3. sh scheduler/restore.sh ./backups/stockdb_YYYYMMDD_HHMMSS.dump
#   4. docker compose up -d --build              # 起其餘服務
#   5. （選用）docker compose run --rm -v stock_ml_models:/app/models ml train   # 重建模型
#
# 原理：drop 並重建空 stockdb（避開 init schema 衝突）→ TimescaleDB pre/post_restore 包住 pg_restore。
# roles(stock_app/stock_readonly) 為 cluster 全域、drop database 不影響；ACL/grants 隨 dump 還原。
set -e
DUMP="$1"
[ -n "$DUMP" ] && [ -f "$DUMP" ] || { echo "用法: sh scheduler/restore.sh <備份檔.dump>"; exit 1; }
C=stock-timescaledb; U=stock_admin; DB=stockdb

echo "→ 中斷現有連線、重建空資料庫 $DB"
docker exec "$C" psql -U "$U" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid<>pg_backend_pid();" >/dev/null || true
docker exec "$C" psql -U "$U" -d postgres -c "DROP DATABASE IF EXISTS $DB;"
docker exec "$C" psql -U "$U" -d postgres -c "CREATE DATABASE $DB;"

echo "→ 建 TimescaleDB 擴充 + pre_restore"
docker exec "$C" psql -U "$U" -d "$DB" -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
docker exec "$C" psql -U "$U" -d "$DB" -c "SELECT timescaledb_pre_restore();"

echo "→ 還原資料（pg_restore；過程中 'extension already exists' 等提示屬正常）"
docker exec -i "$C" pg_restore -U "$U" -d "$DB" --no-owner < "$DUMP" || true

echo "→ post_restore + ANALYZE"
docker exec "$C" psql -U "$U" -d "$DB" -c "SELECT timescaledb_post_restore();"
docker exec "$C" psql -U "$U" -d "$DB" -c "ANALYZE;" >/dev/null 2>&1 || true

echo "✓ 還原完成。驗證："
docker exec "$C" psql -U "$U" -d "$DB" -tAc \
  "SELECT 'symbols='||count(*) FROM symbols UNION ALL SELECT 'daily_prices='||count(*) FROM daily_prices UNION ALL SELECT 'analyses='||count(*) FROM analyses;"
echo "接著：docker compose up -d --build（起其餘服務）"
