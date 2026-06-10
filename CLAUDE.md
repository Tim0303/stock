# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ✅ **狀態：已實作並持續演進（最後更新 2026-06-10）。** 整條學習迴路端到端運作。
> **以下為「目前磁碟/DB 現況」（與下方原始藍圖有差異時以此為準）；動手前先讀對應檔案。**
>
> **服務（`docker-compose.yml`）**：常駐 `timescaledb`/`mcp`/`api`/`web`/`scheduler`；profile=tools 一次性容器
> `loader`/`chiploader`/`ml`/`vcp`。port：7001 MCP / 7002 DB / 7003 API / 7004 戰情儀表板。
> `scheduler` 容器掛 docker socket、crond 每天 15:00 TPE 跑 `scheduler/daily_scan.sh`（行情增量→還原→各分析師記錄→快照→評分）。
>
> **行情來源 = FinMind**（非 yfinance；台股日線/名稱/產業/籌碼皆走 FinMind）。**universe ≈ 300 檔×10Y** 真實日線。
> **還原權值 = 前復權**：`daily_prices.adj_factor`，**最新一筆=1.0、歷史<1.0**（現價=實際成交價）；指標/策略/評分一律用 `price*adj_factor`。
>
> **db/init 實際編號**：01_extensions / 02_roles / 03_core / 05_learning / 06_grants / 07_jobs / 08_indicators /
> 09_chips / 10_strategy_5_10_20 / 11_scan_evolve / 12_backtest / 13_adjust(還原權值) / 14_strategy_box /
> 15_vcp_watchlist / 16_daily_recommendations / 17_support_reclaim(spring) / 18_market_regime / 19_bracket_scoring /
> 20_bb_trend(布林通道趨勢續抱)。
>
> **分析師現況（共用 `analyses`、同台比較）**：儀表板 5 位＝`strat-vcp` / `strat-5-10-20` / `strat-spring`(破支撐拉回) /
> `strat-bb-trend`(布林通道趨勢續抱) / `ml-logreg`。
> ★ `strat-bb-trend` = **5-10-20 進場 + 趨勢續抱出場**（站上20MA續抱／跌破20MA出／−8%停損／maxhold60）。與 5-10-20 共用進場，
>   故**不走 bracket 評分**：主 `evaluate_due_predictions()` 已 `AND skill<>'strat-bb-trend'` 排除，改由 `evaluate_bb_trend()` 評分。
>   實證：per-signal 期望值≈5-10-20（PF1.34 vs 1.33），但勝率低(32% vs 56%)、上檔不封頂(肥尾單撐滿60天 avg+73%)；5槽位組合報酬大幅領先靠肥尾複利、變異大。
> **已退役**：`baseline-momentum`（純對照無用）、`strat-box`（長期 PF≈1.0）——view/資料保留、僅從 API/記錄/snapshot 移除，**勿再加回**。
>
> **評分 = TP/SL bracket（非固定 horizon）**：`evaluate_due_predictions()`（`19_bracket_scoring.sql`）對每筆預測，
> 先到「壓力目標(獲利了結)」或「−8% 停損」或「40 交易日到期」結算，扣 0.6% 成本；目標/停損由 `v_trade_targets` 統一算。
> **大盤過濾**：`market_ok_now()`（`18`，% 個股站上20MA<50% 視為空頭）**僅作風險提示**（看板 badge），
> 弱市照樣開倉/顯示——使用者 2026-06-10 定案改掉硬閘門（記錄函式 10/17/20 與 API 推薦皆已移除 `AND market_ok_now()`）。
> 註：實證上此過濾能提升 PF（spring1.53→2.05、5-10-20 1.37→1.73），改為提示是使用者的產品取捨，非數據結論。
>
> **開發慣例**：改 schema 用 `docker cp NN.sql → docker exec psql -f` 套到運行 DB，**不要 `down -v`**（會刪資料）。
> **回測報告**：統一用 `報告/report_template.ps1` 樣板（白底/正紅負綠/tab/sticky表頭/揭露），輸出到 `報告/`（.gitignore）。
> **實證選股原則**見記憶 `empirical-selection-principles`（成交量看情境、出場決定勝率、趨勢命門、分散>all-in）。

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

**關鍵約定：** 所有「分析師」共用 `analyses` 表、同台比較準確率。多數走統一 bracket 評分；
`strat-bb-trend` 例外走 `evaluate_bb_trend()`（趨勢續抱出場）。
**目前現役 5 位**：`strat-vcp` / `strat-5-10-20` / `strat-spring`（破支撐拉回，`17_support_reclaim.sql`）/
`strat-bb-trend`（布林通道趨勢續抱，`20_bb_trend.sql`，5-10-20進場＋趨勢續抱出場）/ `ml-logreg`；
另有 `strat-box`（`14`）資料保留但已退役。新增任何預測來源都應寫進 `analyses` 才能公平比較。
**勿再加回** `baseline-momentum`、`strat-box`（使用者已決定退役）。

---

## 分析引擎（DB 端，規劃）

技術指標與訊號**在 DB 端用 SQL 窗口函數計算**，而非應用層：

- `db/init/08_indicators.sql` — 技術指標 + 量化統計 + 訊號；自訂 `ema()` aggregate 解 EMA / MACD
- `db/init/10_strategy_5_10_20.sql` — 將 `5-10-20短線順勢進出訊號策略.md` 規則化
  - view `v_strategy_5_10_20` / `v_strategy_latest`（5/10/20MA + 量能 → 進場 A/B/C / 出場 / 0–100 分數 / 評級）
  - function `record_strategy_signals(horizon)` — 把分數 ≥80 的買進訊號寫進 `analyses`（skill=`strat-5-10-20`）→ 走評分迴路

**排程評分：** 評分集中在 DB function `evaluate_due_predictions()`，**現為 TP/SL bracket 法（`19_bracket_scoring.sql`，
已取代 07_jobs 的固定 horizon 版）**：先到「壓力目標/−8%停損/40交易日到期」結算、扣 0.6% 成本，目標/停損由 `v_trade_targets` 統一算。
MCP 工具與每小時 job（`job_evaluate_predictions`）**都呼叫同一個 function**——改評分邏輯只改這一處。
（其他策略檔：`14_strategy_box.sql` 箱型、`17_support_reclaim.sql` 破支撐拉回 spring、`12_backtest.sql` 規則出場回測。）

---

## MCP 工具清單（規劃）

server 名稱 `stock-ai`，權限角色 `stock_app`（查全部、可寫學習表 + 行情表、**無 DELETE/DDL**）：

```
list_tables / describe_table / run_query(唯讀白名單)
get_latest_price / add_symbol
get_indicators / get_signals / scan_signals(選股掃描)
get_chips
get_strategy / scan_strategy / run_strategy_5_10_20
get_vcp_watchlist(VCP 醞釀中/突破監控清單)
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
- **實作差異**：B（回測10MA）回測最差已**停用**（`enable_signal_B=false`），現役只 A、C。
  成交量觀念見記憶 `empirical-selection-principles`：突破(A)要溫和放量、洗盤(spring)要量縮——情境相反。

---

## 資料誠信注意事項

- `06_seed` 為合成假價，只生平日（loader 會以真實日線覆蓋）；不可把 seed 資料當真實行情分析。
- ML 目前資料量小，是 **baseline 展示**，非追 alpha——不要對其準確率做過度推論。
- 美股無籌碼面資料；涉及 `chip_*` 的邏輯需判斷市場別。

---

## 待辦 / 後續

- **減資還原未處理**（不在股利表，worst 回撤可能含減資跳水）。
- **生存者偏差**：回測池僅現存 ~300 檔、無下市股，會高估報酬（尤其空頭年）——報告須揭露。
- **ML 升級**：ml-logreg 僅 9 技術特徵、in-sample ~51%≈擲硬幣；可加情境量(量/50日均量)、距壓力/支撐、大盤寬度、收縮次數等實證特徵。
- 演化器（champion-challenger）尚未自動換冠軍；儀表板標的詳情頁 / WebSocket、對外加認證待補。
