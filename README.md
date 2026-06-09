# 智能 AI 選股平台

AI 持續學習、累積分析技能的台股選股平台（非單純股價 DB）。核心是一條**學習迴路**：
分析（產生預測）→ 到期 → 用真實走勢評分 → 回饋技能庫 → 改進下一次。

> 完整架構/Schema/排程的權威藍圖見 [`CLAUDE.md`](./CLAUDE.md)；
> 實作企劃見 plan 檔；策略規格見 [`5-10-20短線順勢進出訊號策略.md`](./5-10-20短線順勢進出訊號策略.md)。

## 架構（雙介面：AI 走 MCP、人走 REST+前端，全 Docker）

| 服務 | 內容 | Port | 目錄 |
|---|---|---|---|
| timescaledb | PG16 + TimescaleDB（行情 + 學習表） | 7002 | `db/` |
| mcp | FastMCP `stock-ai`（AI 介面） | 7001 | `mcp/` |
| api | FastAPI 唯讀 REST | 7003 | `api/` |
| web | React 戰情儀表板（nginx，/api 同源反代） | 7004 | `web/` |
| loader / chiploader / ml | 一次性工具容器（`profile=tools`） | — | `loader/` `chiploader/` `ml/` |

## 啟動

```powershell
copy .env.example .env          # 填密碼
docker compose up -d --build    # 啟動常駐服務（db / mcp / api / web）

# 一次性工具（行情 / 籌碼 / ML）
docker compose run --rm loader 2330.TW AAPL
docker compose run --rm chiploader 2330.TW
docker compose run --rm ml train
```

## 選股池（universe）

≥50 檔台股、每檔 10Y 內日線、**排除傳產與金融**、保留電子+成長。
13 檔指定白名單優先納入（凌駕產業過濾），其餘按成交量補足。產業別/中文名來自 FinMind `TaiwanStockInfo`。

## 建構進度（subagent / task）

主幹優先：**T0 骨架 → T1 schema → T2 評分 → T3 ingestion → T4 指標 → T5 策略**（里程碑），
再並行 T6 籌碼 / T7 ML / T8 掃描演化 / T9 MCP / T10 API，最後 T11 前端 / T12 整合。
- [x] **T0** 基礎骨架（docker-compose / .env / nginx / db init 編號契約）
- [ ] T1–T12 進行中
