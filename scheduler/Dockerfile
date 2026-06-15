# 每日排程容器：掛 docker socket，內建 busybox crond，每天 15:00 TPE 觸發每日流程
FROM docker:27-cli
RUN apk add --no-cache tzdata
ENV TZ=Asia/Taipei
COPY daily_scan.sh /daily_scan.sh
COPY intraday_scan.sh /intraday_scan.sh
COPY backup.sh /backup.sh
COPY expire_trials.sh /expire_trials.sh
RUN sed -i 's/\r$//' /daily_scan.sh /intraday_scan.sh /backup.sh /expire_trials.sh \
 && chmod +x /daily_scan.sh /intraday_scan.sh /backup.sh /expire_trials.sh \
 && printf '%s\n%s\n%s\n%s\n' \
      "10 13 * * * /intraday_scan.sh >> /var/log/intraday_scan.log 2>&1" \
      "0 15 * * * /daily_scan.sh >> /var/log/daily_scan.log 2>&1" \
      "0 16 * * * /backup.sh >> /var/log/backup.log 2>&1" \
      "30 0 * * * /expire_trials.sh >> /var/log/expire_trials.log 2>&1" \
      > /etc/crontabs/root
# 前景跑 crond（容器常駐）；日誌可用 docker logs stock-scheduler 或 exec 看 /var/log/daily_scan.log
CMD ["crond", "-f", "-l", "8"]
