# chiploader — 台股籌碼 ingestion（owner: loader-agent / T6）

一次性容器（`profile=tools`）。FinMind 來源。連 DB 角色 **stock_app**。美股無籌碼，需正確跳過。

**用法**：`docker compose run --rm chiploader 2330.TW`
**待建**：`Dockerfile`、FinMind 抓取腳本；寫 `chip_institutional`（三大法人）、`chip_margin`（融資券）。

**契約**：僅處理台股；不得修改 docker-compose.yml。
