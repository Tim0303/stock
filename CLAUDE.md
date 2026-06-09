# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ✅ **狀態：已實作並驗證（2026-06-08，T0–T12 完成）。** 七個服務（`docker-compose.yml` + `db/`、`mcp/`、
> `api/`、`web/`、`ml/`、`loader/`、`chiploader/`）皆已落地、整條學習迴路端到端驗證通過。
> **與下方原始藍圖的關鍵差異（以實作為準）：**
> - **行情來源 = FinMind，非 yfinance**：yfinance 對台股 keyless 失效，台股日線/名稱/產業/籌碼統一走 FinMind。
> - **DB 對外 port = 7002**（藍圖部分段落寫 :8000，以 7001 MCP/7002 DB/7003 API/7004 web 為準）。
> - **db/init 實際編號**：01_extensions / 02_roles / 03_core / 05_learning / 06_grants / 07_jobs /
>   08_indicators / 09_chips / 10_strategy_5_10_20 / 11_scan_evolve。
> - **資料**：universe 55 檔×10Y 真實日線（白名單 13 檔 + 流動性補足，補足排序待 FINMIND_TOKEN 修正、含殭屍股）。
> - **開發慣例**：改 schema 用 `psql -f /docker-entrypoint-initdb.d/NN.sql` 套到運行 DB，**不要 `down -v`**（會刪資料）。
> 下方「目標架構 / Schema」仍是有效的設計說明；細節以磁碟現況為準，動手前先讀對應檔案。

---

## 專案定位

`C:\Project\stock` 是一個**智能 AI 選股平台**，核心理念是 **AI 持續學習、累積分析技能**，
而非單純的股價資料庫。所有基礎設施都要服務於「AI 學習迴路」：

```
分析（產生預測） → 等待到期 → 評分（比對實際走勢） → 回饋技能庫 → 改進下一次分析
```

設計 DB schema 或 MCP 工具時，除了行情資料，**必須預留**：分析紀錄、策略/技能庫、
回測與績效、學習結果等表與工具。這是與一般「股價 CRUD」專案最大的差異——不要退化成單純的價格倉儲。

---

## 目標架構（雙介面：AI 走 MCP、人走 REST + 前端）

`docker-compose.yml` 預計包含的服務：

| 服務 | 內容 | 用途 |
|---|---|---|
| `timescaledb` | PG16 + TimescaleDB | 行情 hypertable + 學習表 |
| `mcp` | Python FastMCP，名稱 `stock-ai`（`.mcp.json`） | AI 介面 |
| `api` | FastAPI，**唯讀** REST | 前端資料來源 |
| `web` | React + Vite + Tailwind + ECharts，nginx 部署 | 戰情儀表板 |
| `loader` | yfinance 行情抓取，profile=tools 一次性容器 | 行情 ingestion |
| `chiploader` | FinMind 台股籌碼抓取，profile=tools | 籌碼面（美股無） |
| `ml` | sklearn 訓練 / 預測，profile=tools | ML 預測迴路 |

**Port 規劃（從 7001 起）：**

```
7001  MCP
7002  DB（host 對外）
7003  API
7004  戰情儀表板（人看資料的主入口）
```

nginx 將 `/api` 反向代理到 `api` 服務，同源免 CORS。

---

## 常用指令（規劃，待對應檔案建立後生效）

```powershell
# 啟動整套服務
copy .env.example .env        # 先填密碼
docker compose up -d --build

# 行情 ingestion（一次性容器，已在規劃中驗證可抓真實日線）
docker compose run --rm loader AAPL 2330.TW

# 台股籌碼（FinMind）
docker compose run --rm chiploader 2330.TW

# ML 訓練 / 預測
docker compose run --rm ml train
docker compose run --rm ml predict
```

> 上述指令依賴尚未建立的 `docker-compose.yml` 與各服務 Dockerfile。實作前請勿直接執行。

---

## 資料模型（規劃 Schema）

**行情：**
- `symbols`
- `daily_prices`（TimescaleDB hypertable）

**學習迴路（本專案核心，勿省略）：**
- `skills` — 技能庫，可隨績效演化
- `analyses` — 每次分析 = 一筆預測（記 skill 來源、預測方向、到期日）
- `prediction_outcomes` — 預測準確度評分結果

**台股籌碼面（`db/init/09_chips.sql`，美股無此資料）：**
- `chip_institutional` — 三大法人
- `chip_margin` — 融資券

**Views：**
- `v_due_predictions` — 到期待評分的預測
- `v_skill_performance` — 各技能績效
- `v_price_indicators` / `v_latest_signals` — 技術指標與訊號

**關鍵約定：** 三類「分析師」共用 `analyses` 表、同台比較準確率：
`baseline-momentum` / `ml-logreg` / `strat-5-10-20`。新增任何預測來源都應寫進 `analyses`
並走同一套評分迴路，才能公平比較。

---

## 分析引擎（DB 端，規劃）

技術指標與訊號**在 DB 端用 SQL 窗口函數計算**，而非應用層：

- `db/init/08_indicators.sql` — 技術指標 + 量化統計 + 訊號；自訂 `ema()` aggregate 解 EMA / MACD
- `db/init/10_strategy_5_10_20.sql` — 將 `5-10-20短線順勢進出訊號策略.md` 規則化
  - view `v_strategy_5_10_20` / `v_strategy_latest`（5/10/20MA + 量能 → 進場 A/B/C / 出場 / 0–100 分數 / 評級）
  - function `record_strategy_signals(horizon)` — 把分數 ≥80 的買進訊號寫進 `analyses`（skill=`strat-5-10-20`）→ 走評分迴路

**排程評分：** 評分公式集中在 DB function `evaluate_due_predictions()`（`db/init/07_jobs.sql`）。
MCP 工具與 TimescaleDB 每小時 job（`job_evaluate_predictions`）**都呼叫同一個 function**——
改評分邏輯只改這一處，不要在多處複製。

---

## MCP 工具清單（規劃）

server 名稱 `stock-ai`，權限角色 `stock_app`（查全部、可寫學習表 + 行情表、**無 DELETE/DDL**）：

```
list_tables / describe_table / run_query(唯讀白名單)
get_latest_price / add_symbol
get_indicators / get_signals / scan_signals(選股掃描)
get_chips
get_strategy / scan_strategy / run_strategy_5_10_20
record_analysis / evaluate_predictions / get_accuracy
upsert_skill(技能演化)
```

`run_query` 必須維持唯讀白名單；MCP 角色不得有 DELETE/DDL。

---

## 5-10-20 短線策略（已有文件）

`5-10-20短線順勢進出訊號策略.md` 是目前 repo 唯一實際存在的檔案，為策略的完整規格書。
規則化進 DB 時以該文件為準（C# 偽程式在文件第 18 節）。核心：

- **進場前提：** `Close > 5MA > 10MA > 20MA` 且 20MA 走平或上彎（只做多方結構）
- **進場訊號：** A 突破買 / B 回測 10MA 不破買 / C 重新站回 5MA 買
- **出場：** 跌破 5MA 減碼 ½ → 跌破 10MA 全出 → 跌破 20MA 策略失效
- **訊號分數模型（第 22 節）：** 0–100 分，≥80 買進、60–79 觀察、<60 不進場

---

## 資料誠信注意事項

- `06_seed` 為合成假價，只生平日（loader 會以真實日線覆蓋）；不可把 seed 資料當真實行情分析。
- ML 目前資料量小，是 **baseline 展示**，非追 alpha——不要對其準確率做過度推論。
- 美股無籌碼面資料；涉及 `chip_*` 的邏輯需判斷市場別。

---

## 待辦（規劃）

多檔批次選股流程、回測、儀表板標的詳情頁 / WebSocket、對外加認證。
