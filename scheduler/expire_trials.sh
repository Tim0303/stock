#!/bin/sh
# 試用到期批次（crond 00:30 TPE）：把 trial_end 已過的 trialing 訂閱標成 expired。
# 防禦縱深——gate 在每次請求也會 lazy 標記；此批次讓未活躍用戶的狀態與報表保持乾淨。
C=stock-timescaledb
echo "$(date '+%F %T') expire_trials 開始"
docker exec "$C" psql -U stock_admin -d stockdb -tAc \
  "UPDATE subscriptions SET status='expired', updated_at=now() WHERE status='trialing' AND trial_end <= now();" \
  | sed 's/^/  /' || echo "  (跳過：auth 表尚不存在)"
echo "$(date '+%F %T') expire_trials 完成"
