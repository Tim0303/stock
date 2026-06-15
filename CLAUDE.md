# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> ✅ **狀態：已實作並持續演進（最後更新 2026-06-15）。** 整條學習迴路端到端運作。
> **以下為「目前磁碟/DB 現況」（與下方原始藍圖有差異時以此為準）；動手前先讀對應檔案。**
>
> **服務（`docker-compose.yml`）**：常駐 `timescaledb`/`mcp`/`api`/`web`/`scheduler`；profile=tools 一次性容器
> `loader`/`chiploader`/`ml`/`vcp`。port：7001 MCP / 7002 DB / 7003 API / 7004 戰情儀表板。
> `scheduler` 容器掛 docker socket、crond **三班**：**13:10 TPE `scheduler/intraday_scan.sh`（尾盤即時掃描）** + 15:00 TPE `scheduler/daily_scan.sh` + **16:00 TPE `scheduler/backup.sh`（每日 DB 備份）**。
> **DB 備份**（`scheduler/backup.sh`）：每日 `pg_dump -Fc` → host `./backups/stockdb_*.dump`、`pg_restore -l` 驗證、**保留最近 3 份**（依檔名輪替）；輸出與 DB volume 實體分離、`.gitignore` 排除 `backups/`。**跨機器還原**走 `scheduler/restore.sh <dump>`（drop 重建空庫 + TimescaleDB pre/post_restore；roles 為 cluster 全域、ACL 隨 dump）。模型不在 DB 備份內、可 `ml train` 重建；`.env` 不在備份內、需自行複製。
daily_scan：行情增量→還原→**籌碼增量(三大法人 T86 / 融資融券 MI_MARGN，走 TWSE 依日期端點 chiploader --twse-inst/--twse-margin --days 3，免額度)**→各分析師記錄→快照→評分→**`refresh_analyst_positions()`(刷新持股追蹤)**。
intraday_scan：`loader --intraday`(TWSE MIS 即時報價→今日暫定收盤寫 daily_prices，量張→股×1000)→`vcp watchlist`→`snapshot_eod_signals()`(凍結 5-10-20/spring/bb-trend/vcp 候選到 `eod_intraday_signals`，**純預覽不寫 analyses**)→（有設 `DISCORD_WEBHOOK_URL` 則 curl 推 Discord）。儀表板「尾盤即時訊號」區塊讀 `/api/eod-signals`。
> **分析師持股追蹤**（`24_analyst_positions.sql`）：把各價量分析師訊號當「模擬持股」——`refresh_analyst_positions(p_since 預設2025-12)` **從策略訊號 view 直接推導**(與 analyses 的 backtest/去重解耦)物化到 `analyst_positions` 表：**進場=訊號日隔日開盤**、出場 5-10-20/spring 走 bracket・bb-trend/bb-breakout 走跌破20MA、同檔同策略5日冷卻去重。`v_analyst_positions`(供 `/api/analyst-positions` + 儀表板「分析師持股追蹤」面板)：持有/待進場全顯示、**已平倉只留當月或平倉後7日**。報酬一律台股**紅漲綠跌**(正紅負綠)。ml-logreg/strat-vcp 為模型/Python，暫不納入此追蹤。
>
> **行情來源 = FinMind**（非 yfinance；台股日線/中文名/產業/除權息還原走 FinMind，需 `FINMIND_TOKEN`）。**籌碼與盤中改走 TWSE 公開端點（MI_MARGN/T86/MIS，免 token）**——FinMind token 現在只剩 `loader` 抓行情/還原時用到。**universe ≈ 300 檔×10Y** 真實日線。
> **還原權值 = 前復權**：`daily_prices.adj_factor`，**最新一筆=1.0、歷史<1.0**（現價=實際成交價）；指標/策略/評分一律用 `price*adj_factor`。
>
> **db/init 實際編號**：01_extensions / 02_roles / 03_core / 05_learning / 06_grants / 07_jobs / 08_indicators /
> 09_chips / 10_strategy_5_10_20 / 11_scan_evolve / 12_backtest / 13_adjust(還原權值) / 14_strategy_box /
> 15_vcp_watchlist / 16_daily_recommendations / 17_support_reclaim(spring) / 18_market_regime / 19_bracket_scoring /
> 20_bb_trend(布林通道趨勢續抱) / 21_eod_intraday_signals(尾盤即時訊號快照) / 22_bb_breakout(布林開口放量突破) /
> 23_position_tracker(prediction_outcomes 加 exit_date 出場交易日 + 評分函式 19/20/22 記錄之) /
> 24_analyst_positions(分析師持股追蹤：analyst_positions 表 + refresh_analyst_positions() + v_analyst_positions，供 /api/analyst-positions)。
>
> **分析師現況（共用 `analyses`、同台比較）**：儀表板 6 位＝`strat-vcp` / `strat-5-10-20` / `strat-spring`(破支撐拉回) /
> `strat-bb-trend`(布林通道趨勢續抱) / `strat-bb-breakout`(布林開口放量突破) / `ml-logreg`。
> ★ `strat-bb-breakout`(`22_bb_breakout.sql`) = **收盤>5MA且5MA上彎+衝出布林上軌+帶寬≥1.55×5日前+量≥2.55×20日均量**進場；
>   出場**單一標準=跌破20MA**（無−8%、無時間上限）→ 走專屬 `evaluate_bb_breakout()`，主 evaluate 已 `AND skill<>'strat-bb-breakout'` 排除。
>   回測(現存股)per-signal PF≈1.77、平均+3.36%、肥尾、2022空頭年負；**生存者偏差未修正→樂觀**。比值四捨五入到小數2位後比較。
> ★ `strat-bb-trend` = **5-10-20 進場 + 趨勢續抱出場**（站上20MA續抱／跌破20MA停利／−8%停損／**無時間上限**，2026-06-10 移除原 maxhold60）。與 5-10-20 共用進場，
>   故**不走 bracket 評分**：主 `evaluate_due_predictions()` 已 `AND skill<>'strat-bb-trend'` 排除，改由 `evaluate_bb_trend()` 評分。
>   實證：per-signal 期望值≈5-10-20（PF1.37 vs 1.33），但勝率低(32% vs 56%)、上檔不封頂(肥尾單沿20MA走大波段)；5槽位組合報酬大幅領先(836筆win33%+187萬)靠肥尾複利、變異大。
> ★ `ml-logreg`（2026-06-15 改身分為**「突破成功率模型」**，`ml/main.py`+`ml/features.py`）= **只在布林突破訊號母體上學的 GBDT**：特徵=籌碼(法人吸貨 pre_f/pre_t/pre_tr+融資 pre_mc)+布林(帶寬擴張 bwr/%B/距上軌/5MA斜率/量比)、標籤=該突破 20MA 出場賺否；偵測訊號複用 `v_bb_breakout(is_signal)`(與 strat-bb-breakout 一致)。predict 只在 **proba≥0.40** 寫 `up`(signal_type=`ml-bb`)→等於「**模型過濾後的突破**」分析師，與 strat-bb-breakout(全部突破都進) 並列、各自風險/報酬讓使用者自評。**strat-bb-breakout 不受影響**。評分仍走 bracket(`evaluate_due_predictions`，與他人同口徑)。walk-forward 實證(報告 `布林突破_成功率模型_…`)勝率43%/14x/回撤18%、三項勝基準與手刻濾網；特徵重要性 pre_t(三大法人) 第一。**先前把籌碼焊到「全市場通用模型」無效**(被稀釋 AUC0.617→0.618)，知識要放對母體。舊通用模型 live 預測已於使用者授權下清除(版本重置)。
> **已退役**：`baseline-momentum`（純對照無用）、`strat-box`（長期 PF≈1.0）——view/資料保留、僅從 API/記錄/snapshot 移除，**勿再加回**。
>
> **評分 = TP/SL bracket（非固定 horizon）**：`evaluate_due_predictions()`（`19_bracket_scoring.sql`）對每筆預測，
> 先到「壓力目標(獲利了結)」或「−8% 停損」或「40 交易日到期」結算，扣 0.6% 成本；目標/停損由 `v_trade_targets` 統一算。
> **大盤過濾**：`market_ok_now()`（`18`，% 個股站上20MA<50% 視為空頭）**僅作風險提示**（看板 badge），
> 弱市照樣開倉/顯示——使用者 2026-06-10 定案改掉硬閘門（記錄函式 10/17/20 與 API 推薦皆已移除 `AND market_ok_now()`）。
> 註：實證上此過濾能提升 PF（spring1.53→2.05、5-10-20 1.37→1.73），改為提示是使用者的產品取捨，非數據結論。
>
> **開發慣例**：改 schema 用 `docker cp NN.sql → docker exec psql -f` 套到運行 DB，**不要 `down -v`**（會刪資料）。
> **回測報告**：統一用 `report/report_template.ps1` 樣板（白底/正紅負綠/tab/sticky表頭/揭露），HTML+產生器+引擎全收進 `report/`（**已 .gitignore**；舊 `報告/` 已併入並移除）。產生器走 `docker exec stock-timescaledb psql`/`pg_dump`，重訓/模擬腳本需 DDL 時用 admin 連線(`.env` 的 `POSTGRES_USER/PASSWORD`)。
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
`strat-bb-trend` / `strat-bb-breakout` 例外走各自的 `evaluate_bb_trend()` / `evaluate_bb_breakout()`（皆跌破20MA出場）。
**目前現役 6 位**：`strat-vcp` / `strat-5-10-20` / `strat-spring`（破支撐拉回，`17_support_reclaim.sql`）/
`strat-bb-trend`（布林通道趨勢續抱，`20_bb_trend.sql`，5-10-20進場＋趨勢續抱出場）/
`strat-bb-breakout`（布林開口放量突破，`22_bb_breakout.sql`，突破進場＋跌破20MA出場）/ `ml-logreg`；
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
- ML（ml-logreg）**現為「突破成功率模型」（2026-06-15，見上方 ★ml-logreg）**：只在布林突破訊號母體學
  （籌碼法人吸貨+布林帶寬→該突破 20MA 出場賺否），proba≥0.40 寫 up。**沿革**：原為全市場 bracket 預測
  (LR→GBDT，AUC≈0.57-0.62、門檻0.60-0.70、仍偏 baseline)；把籌碼焊到通用模型無效(被稀釋)，改放對母體才有效。
  模型存 `ml_models` volume(檔名仍 `logreg.pkl`)、daily_scan 每週六重訓、每日 predict。
- 美股無籌碼面資料；涉及 `chip_*` 的邏輯需判斷市場別。

---

## 待辦 / 後續

- **減資還原未處理**（不在股利表，worst 回撤可能含減資跳水）。
- **生存者偏差**：回測池僅現存 ~300 檔、無下市股，會高估報酬（尤其空頭年）——報告須揭露。
- **ML 升級（已完成 2026-06-15）**：ml-logreg 演進為「突破成功率模型」(GBDT，籌碼+布林學突破成敗，門檻0.40，
  walk-forward 勝率43%/14x/回撤18%)；先前 bracket+14特徵通用 GBDT(AUC0.62) 已被取代。後續可試：依大盤調門檻、
  calibration、把成功率模型推廣到其它策略(spring/5-10-20)當「進場品質濾網」。
- 演化器（champion-challenger）尚未自動換冠軍；儀表板標的詳情頁 / WebSocket、對外加認證待補。
