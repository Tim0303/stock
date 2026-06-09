-- 07_jobs.sql — 評分迴路 + 排程 + 種子冠軍（T2, db-schema-agent）
-- 學習迴路的靈魂：評分公式集中在此單一 function，MCP 工具與 TimescaleDB job 都呼叫它。

-- ── 評分 function：對「已到期且未評分」的預測，用 due_date 當天/之後第一個交易日收盤評分 ──
CREATE OR REPLACE FUNCTION evaluate_due_predictions()
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
  n INT;
BEGIN
  WITH due AS (
    SELECT a.analysis_id, a.symbol, a.due_date, a.entry_price, a.direction
    FROM analyses a
    LEFT JOIN prediction_outcomes o ON o.analysis_id = a.analysis_id
    WHERE o.analysis_id IS NULL          -- 尚未評分
      AND a.due_date <= CURRENT_DATE      -- 已到期
      AND a.entry_price IS NOT NULL
  ),
  priced AS (
    SELECT d.*,
      -- 到期日當天或之後第一個交易日的收盤（確保用真實的「未來」價，非 entry 附近）
      (SELECT dp.close FROM daily_prices dp
        WHERE dp.symbol = d.symbol AND dp.ts >= d.due_date
        ORDER BY dp.ts ASC LIMIT 1) AS exit_price
    FROM due d
  )
  INSERT INTO prediction_outcomes (analysis_id, exit_price, realized_return, is_win)
  SELECT
    p.analysis_id,
    p.exit_price,
    CASE WHEN p.entry_price > 0
         THEN ((p.exit_price - p.entry_price) / p.entry_price)::numeric
    END,
    CASE WHEN p.direction = 'long' THEN p.exit_price > p.entry_price
         ELSE p.exit_price < p.entry_price END
  FROM priced p
  WHERE p.exit_price IS NOT NULL;          -- 到期日資料還沒灌到就先跳過，等下次
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;

-- ── 待評分 view ──────────────────────────────────────────────
CREATE OR REPLACE VIEW v_due_predictions AS
SELECT a.analysis_id, a.symbol, a.skill, a.as_of, a.due_date, a.horizon_days, a.entry_price
FROM analyses a
LEFT JOIN prediction_outcomes o ON o.analysis_id = a.analysis_id
WHERE o.analysis_id IS NULL
  AND a.due_date <= CURRENT_DATE;

-- ── 各分析師（skill 家族）績效 view：三方同台比準確率 ─────────────────
CREATE OR REPLACE VIEW v_skill_performance AS
SELECT
  a.skill,
  count(*)                                              AS n_evaluated,
  round(avg(CASE WHEN o.is_win THEN 1 ELSE 0 END), 4)   AS win_rate,
  round(avg(o.realized_return), 5)                       AS avg_return,
  round(
    COALESCE(sum(o.realized_return) FILTER (WHERE o.realized_return > 0), 0)
    / NULLIF(abs(sum(o.realized_return) FILTER (WHERE o.realized_return < 0)), 0)
  , 3)                                                   AS profit_factor
FROM analyses a
JOIN prediction_outcomes o USING (analysis_id)
GROUP BY a.skill;

-- ── 每小時排程：呼叫同一個評分 function（跨時區用到期日判斷最穩）──────────
CREATE OR REPLACE PROCEDURE job_evaluate_predictions(job_id INT, config JSONB)
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM evaluate_due_predictions();
END;
$$;

SELECT add_job('job_evaluate_predictions', schedule_interval => INTERVAL '1 hour');

-- ── 種子冠軍技能：strat-5-10-20 v1（5-10-20 文件預設參數，冷啟動鎖定的基準）──
INSERT INTO skills (family, version, status, market_scope, params, param_hash, created_by, notes)
VALUES (
  'strat-5-10-20', 1, 'champion', 'ALL',
  jsonb_build_object(
    'ma_fast', 5, 'ma_mid', 10, 'ma_slow', 20, 'require_ma20_slope', 'flat_or_up',
    'w_bull_align', 30, 'w_above_ma5', 20, 'w_breakout_5d_high', 20, 'w_volume', 15, 'w_ma20_up', 15,
    'enter_threshold', 80, 'watch_threshold', 60,
    'bias_ma20_max', 0.12, 'bias_ma10_max', 0.08, 'vol_ratio_min', 1.0,
    'enable_signal_A', true, 'enable_signal_B', true, 'enable_signal_C', true, 'pullback_vol_cap', 1.5,
    'horizon_days', 5, 'exit_on_break_ma5', 'half', 'chip_overlay', false
  ),
  'seed-v1', 'system', '5-10-20 短線策略文件預設參數（冠軍基準，演化前凍結）'
)
ON CONFLICT (family, version) DO NOTHING;
