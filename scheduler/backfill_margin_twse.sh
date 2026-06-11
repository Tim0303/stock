#!/bin/bash
# 一次性：用 TWSE MI_MARGN 把融資融券回補到 10 年（依日期、一次一日抓全上市）。
# 設計：
#   1) 先等 TWSE 428 反爬封鎖解除（每 3 分鐘輕量探測 1 次，順帶驗證 20160606 是否回正常資料）
#   2) 解除後以 chiploader 內建 3s 禮貌間隔慢速回補（跳週末/已有資料、428 長退避、異常日記為失敗）
# 可重入：upsert 不重複；失敗/異常日重跑相同指令即可續補。
set -u
cd "$(dirname "$0")/.." || exit 1

APPPW=$(grep -i '^STOCK_APP_PASSWORD=' .env | cut -d= -f2-)
PGUSER=$(grep -i '^POSTGRES_USER=' .env | cut -d= -f2-)
PGDB=$(grep -i '^POSTGRES_DB=' .env | cut -d= -f2-)
DBURL="postgresql://stock_app:${APPPW}@stock-timescaledb:5432/${PGDB}"
UA="User-Agent: Mozilla/5.0"
START="20160611"                 # 約 10 年（與行情對齊）
END="$(date +%Y%m%d)"

cb() { echo "$(date +%s)$RANDOM"; }   # cache-buster（秒+亂數，避免快取舊錯誤回應）

echo "[$(date '+%H:%M:%S')] 等待 TWSE 428 限流解除 ..."
ok=0
for i in $(seq 1 40); do          # 最多等 40×3 分鐘 = 2 小時
  code=$(curl -s -o report/_cool.json -w '%{http_code}' \
    "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=20160606&selectType=STOCK&response=json&_=$(cb)" \
    -H "$UA")
  if [ "$code" = "200" ]; then
    stat=$(python -c "import json;print(json.load(open('report/_cool.json',encoding='utf-8')).get('stat'))" 2>/dev/null)
    echo "[$(date '+%H:%M:%S')] 封鎖解除：http=200，20160606 stat=「$stat」"
    ok=1
    break
  fi
  echo "[$(date '+%H:%M:%S')] 仍被擋 (http $code)，180s 後重探 ($i/40)"
  sleep 180
done
if [ "$ok" != "1" ]; then
  echo "[ABORT] 等 2 小時封鎖仍未解除，先停；稍後重跑本腳本即可續補。"
  exit 2
fi

# 解除後先靜置 30s，再開始慢速回補
sleep 30
echo "[$(date '+%H:%M:%S')] 開始 TWSE 融資融券回補 ${START}~${END}（3s 間隔，跳已有資料）..."
docker run --rm --network stock_default -e DATABASE_URL="$DBURL" \
  stock-chiploader --twse-margin --start "$START" --end "$END" 2>&1 \
  | grep -vE '正視為異常$' | tail -120

echo "===== 回補後現況（融資券）====="
docker exec stock-timescaledb psql -U "$PGUSER" -d "$PGDB" -tAc \
  "SELECT COUNT(*) rows, COUNT(DISTINCT symbol) syms, MIN(ts) min_d, MAX(ts) max_d, COUNT(DISTINCT ts) days FROM chip_margin"
echo "[ALL DONE] $(date '+%Y-%m-%d %H:%M:%S')"
