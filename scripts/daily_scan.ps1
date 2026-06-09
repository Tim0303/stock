# daily_scan.ps1 — 每日自動掃描（Windows 工作排程器掛此腳本，建議台股盤後 15:00 TPE）
# 流程：抓今日行情 → 還原權值 → 五方掃描/監控 → 評分到期預測
# 前提：Docker Desktop 正在執行；於 C:\Project\stock 下有 .env。
$ErrorActionPreference = "Continue"
Set-Location C:\Project\stock
$log = "C:\Project\stock\scripts\daily_scan.log"
function Log($m) { "$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))  $m" | Tee-Object -FilePath $log -Append }

Log "===== 每日掃描開始 ====="

# 1. 抓現有 universe 最新行情（近 1 年增量，upsert 覆蓋最新交易日）
$tickers = (docker exec stock-timescaledb psql -U stock_admin -d stockdb -tAc `
    "SELECT string_agg(symbol,' ' ORDER BY symbol) FROM symbols").Trim() -split '\s+'
Log "抓行情：$($tickers.Count) 檔"
docker compose run --rm loader @tickers --years 1 2>&1 | Select-Object -Last 1 | ForEach-Object { Log $_ }

# 2. 還原權值（更新除權息係數）
docker compose run --rm loader --adjust 2>&1 | Select-Object -Last 1 | ForEach-Object { Log $_ }

# 3. VCP 監控清單（寫今日 vcp_watchlist → 儀表板/MCP 自動顯示）
docker compose run --rm vcp watchlist 2>&1 | Select-Object -Last 1 | ForEach-Object { Log $_ }

# 4. 5-10-20 掃描候選（寫 daily_candidates）
docker exec stock-timescaledb psql -U stock_admin -d stockdb -c "SELECT scan_strategy_candidates();" 2>&1 | ForEach-Object { Log $_ }

# 5. 評分到期預測（學習迴路結算）
docker exec stock-timescaledb psql -U stock_admin -d stockdb -c "SELECT evaluate_due_predictions();" 2>&1 | ForEach-Object { Log $_ }

Log "===== 每日掃描完成 ====="
