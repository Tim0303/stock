-- 16_daily_recommendations.sql — 每日推薦快照 + 前向報酬驗證（learning-loop 補強）
-- 目的：把「儀表板每日推薦的股票」完整記錄下來，往後可驗證命中率、調教策略。
--
-- 與 analyses 的分工：
--   analyses          = 預測（買進級訊號），到期由 evaluate_due_predictions() 評分 → v_skill_performance。
--   daily_recommendations = 儀表板「所見即所記」快照（含 VCP 醞釀中等非買進級），
--                       前向報酬由 v_daily_recommendation_returns 在資料到齊後自動算出。
--
-- 慣例：還原價一律 close*adj_factor（前復權、最新=1.0）；不刪歷史；snapshot 函式冪等（ON CONFLICT upsert）。

-- ── 1) 每日推薦快照表 ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_recommendations (
  rec_date    date    NOT NULL,                 -- 推薦基準日（該檔交易日）
  skill       text    NOT NULL,                 -- strat-5-10-20 / strat-box / strat-vcp / ml-logreg
  symbol      text    NOT NULL,
  name        text,
  score       numeric,
  status      text,                             -- 訊號/狀態（signal_type 或 VCP 醞釀中/待突破/剛突破）
  entry_price numeric,                          -- rec_date 還原收盤（顯示用；驗證以 view 重算為準）
  meta        jsonb   NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (rec_date, skill, symbol)
);
CREATE INDEX IF NOT EXISTS idx_daily_rec_date ON daily_recommendations (rec_date);
CREATE INDEX IF NOT EXISTS idx_daily_rec_skill ON daily_recommendations (skill, rec_date);

COMMENT ON TABLE daily_recommendations IS '每日分析師推薦快照（所見即所記，供日後前向報酬驗證/調教）';

-- 交易計畫欄位（壓力目標 + 停損；目前 5-10-20 / spring 提供，其餘 NULL）
ALTER TABLE daily_recommendations ADD COLUMN IF NOT EXISTS target_price numeric;
ALTER TABLE daily_recommendations ADD COLUMN IF NOT EXISTS stop_price   numeric;

-- ── 2) 快照函式：把當日四位分析師的推薦寫入（冪等 upsert）────────────────
CREATE OR REPLACE FUNCTION snapshot_daily_recommendations()
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
  v_max  date;
  v_total INT := 0;
  n INT;
BEGIN
  SELECT max(ts)::date INTO v_max FROM daily_prices;

  -- 2a) 5-10-20 順勢（買進）
  INSERT INTO daily_recommendations (rec_date, skill, symbol, name, score, status, entry_price, target_price, stop_price)
  SELECT l.ts, 'strat-5-10-20', l.symbol, sy.name, l.score, l.signal_type, round(l.close, 2), l.target_price, l.stop_price
  FROM v_strategy_latest l
  JOIN symbols sy USING (symbol)
  WHERE l.rating = 'buy'
    AND l.ts >= v_max - INTERVAL '5 days'
  ON CONFLICT (rec_date, skill, symbol) DO UPDATE SET
    name = EXCLUDED.name, score = EXCLUDED.score,
    status = EXCLUDED.status, entry_price = EXCLUDED.entry_price,
    target_price = EXCLUDED.target_price, stop_price = EXCLUDED.stop_price;
  GET DIAGNOSTICS n = ROW_COUNT; v_total := v_total + n;

  -- 2b) 箱型區間 strat-box 已退役（長期 PF≈1.0，使用者決定移除）。

  -- 2c) VCP（醞釀中/待突破/剛突破，取最新近期 scan_date）
  IF to_regclass('vcp_watchlist') IS NOT NULL THEN
    INSERT INTO daily_recommendations (rec_date, skill, symbol, name, score, status, entry_price)
    SELECT w.scan_date, 'strat-vcp', w.symbol, w.name, w.score, w.status, round(w.close, 2)
    FROM vcp_watchlist w
    WHERE w.scan_date = (
      SELECT max(scan_date) FROM vcp_watchlist
      WHERE scan_date >= v_max - 7
    )
    ON CONFLICT (rec_date, skill, symbol) DO UPDATE SET
      name = EXCLUDED.name, score = EXCLUDED.score,
      status = EXCLUDED.status, entry_price = EXCLUDED.entry_price;
    GET DIAGNOSTICS n = ROW_COUNT; v_total := v_total + n;
  END IF;

  -- 2d) ML 預測（最新一輪 up，來自 analyses）
  INSERT INTO daily_recommendations (rec_date, skill, symbol, name, score, status, entry_price)
  SELECT a.as_of, 'ml-logreg', a.symbol, sy.name, a.score, a.signal_type, round(a.entry_price, 2)
  FROM analyses a
  JOIN symbols sy USING (symbol)
  WHERE a.skill = 'ml-logreg'
    AND a.predicted = 'up'
    AND (a.meta->>'backtest') IS DISTINCT FROM 'true'
    AND a.as_of = (
      SELECT max(as_of) FROM analyses
      WHERE skill = 'ml-logreg' AND (meta->>'backtest') IS DISTINCT FROM 'true'
    )
  ON CONFLICT (rec_date, skill, symbol) DO UPDATE SET
    name = EXCLUDED.name, score = EXCLUDED.score,
    status = EXCLUDED.status, entry_price = EXCLUDED.entry_price;
  GET DIAGNOSTICS n = ROW_COUNT; v_total := v_total + n;

  -- 2e) 破支撐拉回 spring（第六位分析師）
  IF to_regclass('v_support_reclaim_latest') IS NOT NULL THEN
    INSERT INTO daily_recommendations (rec_date, skill, symbol, name, score, status, entry_price, target_price, stop_price)
    SELECT r.ts, 'strat-spring', r.symbol, sy.name, r.score, 'spring', round(r.close, 2), r.target_price, r.stop_price
    FROM v_support_reclaim_latest r
    JOIN symbols sy USING (symbol)
    WHERE r.signal_type = 'spring' AND r.ts >= v_max - INTERVAL '5 days'
    ON CONFLICT (rec_date, skill, symbol) DO UPDATE SET
      name = EXCLUDED.name, score = EXCLUDED.score,
      status = EXCLUDED.status, entry_price = EXCLUDED.entry_price,
      target_price = EXCLUDED.target_price, stop_price = EXCLUDED.stop_price;
    GET DIAGNOSTICS n = ROW_COUNT; v_total := v_total + n;
  END IF;

  RETURN v_total;
END;
$$;

-- ── 3) 前向報酬驗證 view：每筆推薦 +5/+10/+20 交易日的還原報酬 ────────────
-- 還原收盤 close*adj_factor；以「交易日序號」找未來第 N 根（非日曆日），資料未到齊則為 NULL。
CREATE OR REPLACE VIEW v_daily_recommendation_returns AS
WITH px AS (
  SELECT symbol, ts,
         close * adj_factor AS adj_close,
         row_number() OVER (PARTITION BY symbol ORDER BY ts) AS rn
  FROM daily_prices
  WHERE close > 0
),
rec AS (
  SELECT r.rec_date, r.skill, r.symbol, r.name, r.score, r.status,
         p.rn AS entry_rn, p.adj_close AS entry_adj
  FROM daily_recommendations r
  JOIN px p ON p.symbol = r.symbol AND p.ts = r.rec_date
)
SELECT
  rec.rec_date, rec.skill, rec.symbol, rec.name, rec.score, rec.status,
  round(rec.entry_adj, 2)                                         AS entry_close,
  round(f5.adj_close, 2)                                          AS close_5d,
  round((f5.adj_close  / NULLIF(rec.entry_adj, 0) - 1) * 100, 2)  AS ret_5d_pct,
  round(f10.adj_close, 2)                                         AS close_10d,
  round((f10.adj_close / NULLIF(rec.entry_adj, 0) - 1) * 100, 2)  AS ret_10d_pct,
  round(f20.adj_close, 2)                                         AS close_20d,
  round((f20.adj_close / NULLIF(rec.entry_adj, 0) - 1) * 100, 2)  AS ret_20d_pct
FROM rec
LEFT JOIN px f5  ON f5.symbol  = rec.symbol AND f5.rn  = rec.entry_rn + 5
LEFT JOIN px f10 ON f10.symbol = rec.symbol AND f10.rn = rec.entry_rn + 10
LEFT JOIN px f20 ON f20.symbol = rec.symbol AND f20.rn = rec.entry_rn + 20;

COMMENT ON VIEW v_daily_recommendation_returns IS '每日推薦的 +5/+10/+20 交易日還原報酬（資料到齊後自動算出）';

-- ── 4) 績效彙總 view：依分析師 × 是否到齊，看命中率/平均報酬（調教用）──────────
CREATE OR REPLACE VIEW v_daily_recommendation_perf AS
SELECT
  skill,
  count(*)                                              AS n_total,
  count(ret_20d_pct)                                    AS n_matured_20d,
  round(avg(ret_5d_pct), 2)                             AS avg_ret_5d,
  round(avg(ret_10d_pct), 2)                            AS avg_ret_10d,
  round(avg(ret_20d_pct), 2)                            AS avg_ret_20d,
  round(avg((ret_20d_pct > 0)::int)::numeric * 100, 1)  AS win_rate_20d_pct
FROM v_daily_recommendation_returns
GROUP BY skill
ORDER BY skill;

COMMENT ON VIEW v_daily_recommendation_perf IS '每日推薦命中率/平均前向報酬彙總（依分析師）';

-- ── 5) 權限：stock_app 可寫、stock_readonly 唯讀 ────────────────────────
GRANT SELECT, INSERT, UPDATE ON daily_recommendations TO stock_app;
GRANT SELECT ON daily_recommendations TO stock_readonly;
GRANT EXECUTE ON FUNCTION snapshot_daily_recommendations() TO stock_app;
GRANT SELECT ON v_daily_recommendation_returns TO stock_app, stock_readonly;
GRANT SELECT ON v_daily_recommendation_perf TO stock_app, stock_readonly;
