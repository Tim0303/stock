-- 19_bracket_scoring.sql — TP/SL bracket 正式評分出場（取代固定 horizon），全分析師統一。
-- 出場：進場後最早觸發者——high>=目標(壓力下緣) 視為達標(win)；low<=停損(−8%) 視為停損；
--       maxhold(40交易日) 內都沒觸發 → 到期收盤結算。扣 0.6% 來回成本。
-- 目標/停損對「任一檔任一日」統一由 v_trade_targets 算（res60 壓力邏輯），與看板顯示一致。
-- 還原價 close*adj_factor；比率對進場日還原收盤，scale-invariant。

CREATE OR REPLACE VIEW v_trade_targets AS
WITH p AS (
  SELECT symbol, ts, close*adj_factor AS entry_close,
    max(high*adj_factor) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) AS res60
  FROM daily_prices WHERE close > 0
)
SELECT symbol, ts, round(entry_close,2) AS entry_close,
  CASE WHEN res60 > entry_close*1.01 THEN round(LEAST(res60*0.99, entry_close*1.25),2)
       ELSE round(entry_close*1.15,2) END                                AS target_price,
  round(entry_close*0.92,2)                                              AS stop_price
FROM p;
GRANT SELECT ON v_trade_targets TO stock_app, stock_readonly;

-- ── bracket 評分（取代固定 horizon）──────────────────────────────────────────
-- 先移除舊的無參數版，避免與新版(帶 default)同名簽名衝突。
DROP FUNCTION IF EXISTS evaluate_due_predictions();
CREATE OR REPLACE FUNCTION evaluate_due_predictions(p_maxhold INT DEFAULT 40, p_cost NUMERIC DEFAULT 0.006)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE n INT;
BEGIN
  CREATE TEMP TABLE _px ON COMMIT DROP AS
    SELECT symbol, ts,
           high*adj_factor AS hi, low*adj_factor AS lo, close*adj_factor AS cl,
           row_number() OVER (PARTITION BY symbol ORDER BY ts) AS rn
    FROM daily_prices WHERE close > 0;
  CREATE INDEX ON _px(symbol, rn);
  CREATE INDEX ON _px(symbol, ts);

  INSERT INTO prediction_outcomes (analysis_id, exit_price, exit_date, realized_return, is_win, notes)
  SELECT
    a.analysis_id,
    x.exit_price,
    x.exit_date,
    round((x.exit_price / e.cl - 1) - p_cost, 5)                     AS realized_return,
    ((x.exit_price / e.cl - 1) - p_cost) > 0                         AS is_win,
    x.reason
  FROM analyses a
  LEFT JOIN prediction_outcomes o ON o.analysis_id = a.analysis_id
  JOIN _px e            ON e.symbol = a.symbol AND e.ts = a.as_of
  JOIN v_trade_targets t ON t.symbol = a.symbol AND t.ts = a.as_of
  CROSS JOIN LATERAL (
    WITH fwd AS (
      SELECT i.rn, i.ts, i.cl, (i.lo <= t.stop_price) AS sl, (i.hi >= t.target_price) AS tp
      FROM _px i WHERE i.symbol = a.symbol AND i.rn > e.rn AND i.rn <= e.rn + p_maxhold
    ),
    first_hit AS (   -- 先到先出（同日先判停損，保守）
      SELECT CASE WHEN sl THEN t.stop_price ELSE t.target_price END AS exit_price, ts AS exit_date,
             CASE WHEN sl THEN 'stop' ELSE 'target' END             AS reason
      FROM fwd WHERE sl OR tp ORDER BY rn LIMIT 1
    ),
    matured AS (     -- 沒觸發但 maxhold 已過 → 到期收盤；資料未滿則無列（留待下次）
      SELECT cl AS exit_price, ts AS exit_date, 'timeout' AS reason
      FROM _px WHERE symbol = a.symbol AND rn = e.rn + p_maxhold
    )
    SELECT exit_price, exit_date, reason FROM first_hit
    UNION ALL
    SELECT exit_price, exit_date, reason FROM matured WHERE NOT EXISTS (SELECT 1 FROM first_hit)
    LIMIT 1
  ) x
  WHERE o.analysis_id IS NULL
    AND a.skill <> 'strat-bb-trend';   -- 趨勢續抱另由 evaluate_bb_trend() 評分（跌破20MA，非 bracket）
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;
GRANT EXECUTE ON FUNCTION evaluate_due_predictions(INT, NUMERIC) TO stock_app;
