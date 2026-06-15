#!/bin/sh
# 每日資料庫備份（crond 16:00 TPE，daily_scan 完成後）。
# pg_dump custom 格式 → /backups（host 掛載 ./backups），保留最近 3 份。
# 還原（另一台機器）見 scheduler/restore.sh。
set -e
C=stock-timescaledb; U=stock_admin; DB=stockdb
TS=$(date '+%Y%m%d_%H%M%S')
OUT="/backups/stockdb_${TS}.dump"
mkdir -p /backups
echo "$(date '+%F %T') 備份開始 → $OUT"

# pg_dump 在 timescaledb 容器內跑（trust 本機連線），-Fc 二進位串流回來寫進掛載目錄。
docker exec "$C" pg_dump -U "$U" -Fc -d "$DB" > "$OUT"

# 完整性檢查：pg_restore -l 能列出 TOC 才算有效，否則刪半成品並失敗離開。
if docker exec -i "$C" pg_restore -l < "$OUT" >/dev/null 2>&1; then
  echo "$(date '+%F %T') 備份完成 ($(wc -c < "$OUT") bytes)"
else
  echo "$(date '+%F %T') ⚠ 備份檔驗證失敗，刪除 $OUT"; rm -f "$OUT"; exit 1
fi

# 輪替：只留最近 3 份（依檔名時間戳排序，字典序＝時間序，比 mtime 穩健）
ls -1 /backups/stockdb_*.dump 2>/dev/null | sort -r | tail -n +4 | xargs -r rm -f
echo "$(date '+%F %T') 現存備份："; ls -1 /backups/stockdb_*.dump 2>/dev/null | sort -r || true
