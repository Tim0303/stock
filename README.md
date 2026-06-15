# 智能 AI 選股平台

AI 持續學習、累積分析技能的台股選股**資訊平台**（非單純股價 DB，亦**非投資建議**）。核心是一條**學習迴路**：
分析（產生預測）→ 到期 → 用真實走勢評分 → 回饋技能庫 → 改進下一次。

> 完整架構 / Schema / 排程的權威藍圖見 [`CLAUDE.md`](./CLAUDE.md)；策略規格見 [`5-10-20短線順勢進出訊號策略.md`](./5-10-20短線順勢進出訊號策略.md)。

## 架構（雙介面：AI 走 MCP、人走 REST + 前端，全 Docker）

| 服務 | 內容 | Port | 目錄 |
|---|---|---|---|
| timescaledb | PG16 + TimescaleDB（行情 + 學習表 + 帳號/訂閱表） | 7002 | `db/` |
| mcp | FastMCP `stock-ai`（AI 介面，角色 `stock_app`） | 7001 | `mcp/` |
| api | FastAPI REST（股票唯讀 `stock_readonly` + 認證 `stock_auth`） | 7003 | `api/` |
| web | React 戰情儀表板（nginx，/api 同源反代） | 7004 | `web/` |
| scheduler | 常駐 crond：盤中掃描 / 每日掃描 / DB 備份 / 試用到期 | — | `scheduler/` |
| loader / chiploader / ml | 一次性工具容器（`profile=tools`） | — | `loader/` `chiploader/` `ml/` |

## 啟動

```powershell
copy .env.example .env          # 填密碼、JWT_SECRET、STOCK_AUTH_PASSWORD 等
docker compose up -d --build    # 啟動常駐服務（db / mcp / api / web / scheduler）

# 一次性工具（行情 / 籌碼 / ML）
docker compose run --rm loader 2330.TW
docker compose run --rm chiploader 2330.TW
docker compose run --rm ml train       # 訓練 ml-logreg（突破成功率模型）
```

開 **http://localhost:7004** → 行銷頁 → 免費註冊（14 天試用）→ 登入後進 `/app` 戰情儀表板。

## 訂閱制：登入 / 註冊 + 免費試用（Phase 1）

整站需登入才可看；先免費試用、之後轉付費（Phase 2 接綠界/藍新 信用卡定期定額 + LINE Pay）。

- **自建 auth**（`api/auth.py`）：argon2 雜湊、JWT(HttpOnly cookie)、Email 驗證、密碼重設、CSRF、rate-limit。
- **閘門**：`app.py` middleware 鎖所有 `/api` 資料端點（公開：`/api/health`、`/api/auth/*`、docs）。未登入→401、試用到期/未驗證→402/403。
- **PII 最小權限**：帳號/訂閱表只授權給 `stock_auth`（碰不到股票資料）；`stock_app`/`stock_readonly` 碰不到 PII（見 `db/init/25_auth.sql`）。
- **試用狀態機**：註冊建 `trialing`(14天)；gate 每次請求 lazy 標到期；`scheduler` 00:30 批次清。付款 webhook 預留（Phase 2 翻 `active`）。
- **dev 寄信**：`EMAIL_BACKEND=console` → 驗證/重設連結印在 `docker logs stock-api`（prod 切 SMTP）。
- ⚠ 正式上線：`COOKIE_SECURE=true` + HTTPS；需營業登記 + 電子發票 + 法律文件，詳見 `CLAUDE.md` 待辦。

## 分析師（共用 `analyses`、同台比較）

儀表板 6 位：`strat-5-10-20` / `strat-spring`（破支撐拉回）/ `strat-vcp`（波動收縮突破）/
`strat-bb-trend`（布林趨勢續抱）/ `strat-bb-breakout`（布林開口放量突破）/ `ml-logreg`（**突破成功率模型**：
只在突破訊號母體學籌碼+布林，proba≥0.40 才看多＝「模型過濾後的突破」）。
評分走統一 TP/SL bracket（`evaluate_due_predictions`）；bb-trend/bb-breakout 走各自跌破 20MA 評分。

## 排程（scheduler crond，TPE）

- **13:10** 尾盤即時掃描（TWSE MIS 即時報價 → 暫定盤 → 訊號 → 儀表板/Discord）
- **15:00** 每日掃描（行情/籌碼增量 → 各分析師記錄 → 評分 → 持股追蹤刷新）
- **16:00** DB 備份（`pg_dump -Fc` → `./backups`，保留 3 份；跨機器還原走 `scheduler/restore.sh`）
- **00:30** 試用到期批次

## 選股池（universe）

≈300 檔台股、每檔 10Y 內日線。產業別/中文名來自 FinMind `TaiwanStockInfo`；籌碼/盤中走 TWSE 公開端點（免 token）。
**還原權值＝前復權**（`daily_prices.adj_factor`，最新=1.0、歷史<1.0）；指標/策略/評分一律用 `price*adj_factor`。

## 免責

本平台為**資訊與教育工具**，提供技術分析訊號、回測與統計資訊，**非投資建議、非個股買賣推薦**。
所有內容含模型誤差與生存者偏差，過去績效不代表未來。投資決策與風險請自行評估與承擔。
