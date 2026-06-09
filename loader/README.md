# loader — 行情 ingestion + 選股池建構（owner: loader-agent / T3）

一次性容器（`profile=tools`）。連 DB 角色 **stock_app**。

**用法**：`docker compose run --rm loader 2330.TW AAPL`
**待建**：`Dockerfile`、yfinance 抓取腳本（台股 `.TW`/`.TWO`）、universe 建構。

**universe 規則**（見 plan〇章 / 記憶 stock-universe-selection）：
- 白名單 13 檔優先（凌駕產業過濾）：6658 8028 2317 2489 6213 5434 2330 4977 2327 2458 1815 3163 3363
- 排除金融+傳產後，按成交量補足到 ≥50 檔
- 每檔抓近 10Y 日線；中文名/產業別來自 FinMind `TaiwanStockInfo`，**代號對應一律查證不臆測**

**契約**：寫 daily_prices/symbols 用 stock_app；不得修改 docker-compose.yml。
