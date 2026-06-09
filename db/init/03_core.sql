-- 03_core.sql — 行情核心（T1, db-schema-agent）
-- symbols（標的主檔，含中文名/產業別/白名單旗標）+ daily_prices（hypertable）

CREATE TABLE IF NOT EXISTS symbols (
  symbol             TEXT PRIMARY KEY,         -- yfinance 代號：台股 2330.TW / 上櫃 .TWO；美股 AAPL
  name               TEXT,                     -- 中文名（FinMind TaiwanStockInfo，台股）
  market             TEXT NOT NULL,            -- 'TW' / 'US'
  industry_category  TEXT,                     -- FinMind 產業別（台股；universe 過濾依據）
  is_whitelist       BOOLEAN NOT NULL DEFAULT FALSE,  -- universe 13 檔指定白名單
  added_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON COLUMN symbols.name IS '中文名一律以 FinMind 查證後填入，絕不臆測';

CREATE TABLE IF NOT EXISTS daily_prices (
  symbol  TEXT  NOT NULL REFERENCES symbols(symbol),
  ts      DATE  NOT NULL,
  open    NUMERIC,
  high    NUMERIC,
  low     NUMERIC,
  close   NUMERIC,
  volume  BIGINT,
  PRIMARY KEY (symbol, ts)   -- 含分區鍵 ts，符合 hypertable 要求
);

-- 轉 hypertable，依年分塊（10Y 日線 → 約 10 chunk/檔）
SELECT create_hypertable('daily_prices', 'ts',
  chunk_time_interval => INTERVAL '1 year',
  if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol_ts ON daily_prices (symbol, ts DESC);
