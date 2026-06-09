-- 05_learning.sql — 學習迴路核心表（T1, db-schema-agent）
-- skills（技能=策略家族+參數版本+績效快照）/ analyses（每次分析=一筆預測）/ prediction_outcomes（評分）

-- ── 技能庫（可演化：family + version，champion-challenger）──────────────
CREATE TABLE IF NOT EXISTS skills (
  skill_id          BIGSERIAL PRIMARY KEY,
  family            TEXT NOT NULL,            -- 'strat-5-10-20' / 'baseline-momentum' / 'ml-logreg'
  version           INT  NOT NULL,
  parent_skill_id   BIGINT REFERENCES skills(skill_id),  -- 演化譜系
  status            TEXT NOT NULL DEFAULT 'candidate',   -- champion/challenger/retired/candidate
  market_scope      TEXT NOT NULL DEFAULT 'ALL',         -- TW/US/ALL
  params            JSONB NOT NULL DEFAULT '{}'::jsonb,  -- 參數空間（見 plan 二-A）
  param_hash        TEXT,                                -- params 正規化雜湊，防重複候選
  -- 績效快照（由 T2 評分/T8 演化回填，避免每次重算）
  n_predictions     INT DEFAULT 0,
  win_rate          NUMERIC,
  avg_return        NUMERIC,
  profit_factor     NUMERIC,
  payoff_ratio      NUMERIC,
  sharpe_like       NUMERIC,
  max_drawdown      NUMERIC,
  oos_win_rate      NUMERIC,
  last_evaluated_at TIMESTAMPTZ,
  -- 治理
  created_by        TEXT DEFAULT 'system',   -- system/auto-grid/llm/human
  notes             TEXT,                    -- LLM 寫的假設與失效解讀
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (family, version),
  UNIQUE (family, param_hash)
);
CREATE INDEX IF NOT EXISTS idx_skills_family_status ON skills (family, status);

-- ── 分析＝預測（三類分析師共用；以 skill 字串同台比較，skill_id 指向具體參數版本）──
CREATE TABLE IF NOT EXISTS analyses (
  analysis_id   BIGSERIAL PRIMARY KEY,
  symbol        TEXT NOT NULL REFERENCES symbols(symbol),
  skill         TEXT NOT NULL,               -- 分析師家族字串（三方比較鍵）
  skill_id      BIGINT REFERENCES skills(skill_id),  -- 具體參數版本（strat 必填；ml/baseline 可空）
  as_of         DATE NOT NULL,               -- 分析基準日（用此日收盤資料）
  horizon_days  INT  NOT NULL,               -- 預測 N 日
  due_date      DATE NOT NULL,               -- 到期評分日
  direction     TEXT NOT NULL DEFAULT 'long',-- long/short
  predicted     TEXT,                        -- 'up'/'down' 預測方向
  score         NUMERIC,                     -- 0-100 策略分（strat）或機率（ml）
  signal_type   TEXT,                        -- 進場訊號 A/B/C（strat）
  entry_price   NUMERIC,                     -- as_of 收盤價（評分基準）
  meta          JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_analyses_skill_asof ON analyses (skill, as_of);
CREATE INDEX IF NOT EXISTS idx_analyses_symbol_asof ON analyses (symbol, as_of);
CREATE INDEX IF NOT EXISTS idx_analyses_due ON analyses (due_date);

-- ── 預測評分結果（到期後由 evaluate_due_predictions() 寫入）────────────────
CREATE TABLE IF NOT EXISTS prediction_outcomes (
  analysis_id      BIGINT PRIMARY KEY REFERENCES analyses(analysis_id),
  evaluated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  exit_price       NUMERIC,                  -- due_date 收盤價
  realized_return  NUMERIC,                  -- (exit-entry)/entry（long）
  is_win           BOOLEAN,                  -- 預測方向是否正確
  notes            TEXT
);
