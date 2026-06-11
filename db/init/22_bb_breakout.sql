-- 22_bb_breakout.sql — 布林開口放量突破策略 strat-bb-breakout（第六位分析師）
-- 進場：收盤>5MA 且 5MA上彎 + 收盤衝出布林上軌(20MA+2σ) + 帶寬(4σ)≥1.55×5日前 + 量≥2.55×20日均量
--       （比值四捨五入到小數2位後比較，與實證一致）。
-- 出場：★單一標準＝收盤跌破 20MA（同時當停利與停損，無 −8%、無時間上限）。
-- 評分不混 bracket：見 evaluate_bb_breakout()；主 evaluate_due_predictions() 已排除本 skill。
-- 回測(2016-26,~300檔現存股)：per-signal PF≈1.77、平均+3.36%、肥尾；唯空頭年(2022)為負。生存者偏差未修正→樂觀。

INSERT INTO skills (family, version, status, market_scope, params, param_hash, created_by, notes)
VALUES ('strat-bb-breakout', 1, 'champion', 'ALL',
  jsonb_build_object('entry','bb_upper_breakout','bw_expand',1.55,'vol_mult',2.55,
                     'exit','ma20_break','stop','none','maxhold','none'),
  'seed-bbbreakout-v1','human',
  '布林開口放量突破：收盤>5MA且5MA上彎+衝出布林上軌+帶寬≥1.55×5日前+量≥2.55×20日均量；出場單一標準=跌破20MA。回測PF≈1.77、肥尾、2022空頭年負。')
ON CONFLICT (family, version) DO NOTHING;

-- 全歷史訊號 view（布林開口放量突破 + 0-100 分數）
CREATE OR REPLACE VIEW v_bb_breakout AS
WITH adj AS (
  SELECT symbol, ts, volume, close*adj_factor AS c
  FROM daily_prices WHERE close>0
),
b AS (
  SELECT symbol, ts, c, volume,
    avg(c) OVER w5 AS ma5, avg(c) OVER w20 AS ma20, stddev_pop(c) OVER w20 AS std20,
    avg(volume) OVER w20 AS vol_ma20, count(*) OVER w20 AS nwin
  FROM adj
  WINDOW w5  AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 4  PRECEDING AND CURRENT ROW),
         w20 AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 19 PRECEDING AND CURRENT ROW)
),
b2 AS (
  SELECT *, lag(ma5) OVER w AS ma5p, (ma20+2*std20) AS bbu, (4*std20) AS bw,
           lag(4*std20,5) OVER w AS bw5
  FROM b WINDOW w AS (PARTITION BY symbol ORDER BY ts)
)
SELECT symbol, ts, round(c,2) AS close, round(ma20,2) AS ma20,
  CASE WHEN vol_ma20>0 THEN round((volume/vol_ma20)::numeric,2) END AS vol_ratio,
  CASE WHEN bw5>0     THEN round((bw/bw5)::numeric,2)         END AS bw_ratio,
  (nwin>=20 AND c>ma5 AND ma5>ma5p AND c>bbu
     AND bw5>0     AND round((bw/bw5)::numeric,2)     >= 1.55
     AND vol_ma20>0 AND round((volume/vol_ma20)::numeric,2) >= 2.55) AS is_signal,
  CASE WHEN vol_ma20>0 AND bw5>0 THEN
    round(LEAST(100, 55 + LEAST(28,(volume/vol_ma20-2.55)*8) + LEAST(17,(bw/bw5-1.55)*22)))::int
  END AS score
FROM b2;
GRANT SELECT ON v_bb_breakout TO stock_app, stock_readonly;

-- 近 5 日內每檔最新一筆突破訊號（給記錄/儀表板）
CREATE OR REPLACE VIEW v_bb_breakout_latest AS
SELECT DISTINCT ON (symbol)
  symbol, ts, score, 'breakout' AS signal_type, close AS entry_price,
  vol_ratio, bw_ratio, ma20 AS exit_level, '跌破20MA 出場' AS exit_rule
FROM v_bb_breakout
WHERE is_signal AND ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
ORDER BY symbol, ts DESC;
GRANT SELECT ON v_bb_breakout_latest TO stock_app, stock_readonly;

-- 記錄：把近日突破訊號寫進 analyses（skill=strat-bb-breakout）
CREATE OR REPLACE FUNCTION record_bb_breakout_signals()
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE n INT; v_skill_id BIGINT;
BEGIN
  SELECT skill_id INTO v_skill_id FROM skills
  WHERE family='strat-bb-breakout' AND status='champion' ORDER BY version DESC LIMIT 1;
  INSERT INTO analyses
    (symbol, skill, skill_id, as_of, horizon_days, due_date,
     direction, predicted, score, signal_type, entry_price, meta)
  SELECT l.symbol, 'strat-bb-breakout', v_skill_id, l.ts, 5,
    l.ts + make_interval(days => 365),        -- 無 maxhold；due_date 僅供參考(出場才結算)
    'long', 'up', l.score, l.signal_type, l.entry_price,
    jsonb_build_object('exit_type','ma20_break','stop','none',
                       'vol_ratio',l.vol_ratio,'bw_ratio',l.bw_ratio)
  FROM v_bb_breakout_latest l
  WHERE NOT EXISTS (SELECT 1 FROM analyses a
    WHERE a.symbol=l.symbol AND a.skill='strat-bb-breakout' AND a.as_of=l.ts);
  GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
END $$;
GRANT EXECUTE ON FUNCTION record_bb_breakout_signals() TO stock_app;

-- 專屬評分：跌破20MA 出場（單一標準，無 −8%、無到期）；仍未跌破者維持未評分。
DROP FUNCTION IF EXISTS evaluate_bb_breakout(INT, NUMERIC);
CREATE OR REPLACE FUNCTION evaluate_bb_breakout(p_scan INT DEFAULT 2000, p_cost NUMERIC DEFAULT 0.006)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE n INT;
BEGIN
  CREATE TEMP TABLE _px ON COMMIT DROP AS
    SELECT symbol, ts, close*adj_factor AS cl, row_number() OVER (PARTITION BY symbol ORDER BY ts) AS rn
    FROM daily_prices WHERE close>0;
  CREATE INDEX ON _px(symbol, rn); CREATE INDEX ON _px(symbol, ts);
  CREATE TEMP TABLE _m ON COMMIT DROP AS
    SELECT symbol, ts, ma20 FROM v_price_indicators WHERE n_window>=20 AND ma20 IS NOT NULL;
  CREATE INDEX ON _m(symbol, ts);

  INSERT INTO prediction_outcomes (analysis_id, exit_price, realized_return, is_win, notes)
  SELECT a.analysis_id, x.exit_price,
    round((x.exit_price/e.cl - 1) - p_cost, 5),
    ((x.exit_price/e.cl - 1) - p_cost) > 0, 'ma20_break'
  FROM analyses a
  LEFT JOIN prediction_outcomes o ON o.analysis_id=a.analysis_id
  JOIN _px e ON e.symbol=a.symbol AND e.ts=a.as_of
  CROSS JOIN LATERAL (   -- 第一個收盤跌破20MA 的交易日；沒有 → 無列(未平倉，留待下次)
    SELECT i.cl AS exit_price
    FROM _px i JOIN _m m ON m.symbol=i.symbol AND m.ts=i.ts
    WHERE i.symbol=a.symbol AND i.rn>e.rn AND i.rn<=e.rn+p_scan AND i.cl < m.ma20
    ORDER BY i.rn LIMIT 1
  ) x
  WHERE a.skill='strat-bb-breakout' AND o.analysis_id IS NULL;
  GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
END $$;
GRANT EXECUTE ON FUNCTION evaluate_bb_breakout(INT, NUMERIC) TO stock_app;

-- 主 bracket 評分排除本 skill（與 strat-bb-trend 同，走專屬 evaluate）
DROP FUNCTION IF EXISTS evaluate_due_predictions();
CREATE OR REPLACE FUNCTION evaluate_due_predictions(p_maxhold INT DEFAULT 40, p_cost NUMERIC DEFAULT 0.006)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE n INT;
BEGIN
  CREATE TEMP TABLE _px ON COMMIT DROP AS
    SELECT symbol, ts, high*adj_factor AS hi, low*adj_factor AS lo, close*adj_factor AS cl,
           row_number() OVER (PARTITION BY symbol ORDER BY ts) AS rn
    FROM daily_prices WHERE close > 0;
  CREATE INDEX ON _px(symbol, rn); CREATE INDEX ON _px(symbol, ts);

  INSERT INTO prediction_outcomes (analysis_id, exit_price, realized_return, is_win, notes)
  SELECT a.analysis_id, x.exit_price,
    round((x.exit_price / e.cl - 1) - p_cost, 5),
    ((x.exit_price / e.cl - 1) - p_cost) > 0, x.reason
  FROM analyses a
  LEFT JOIN prediction_outcomes o ON o.analysis_id = a.analysis_id
  JOIN _px e             ON e.symbol = a.symbol AND e.ts = a.as_of
  JOIN v_trade_targets t ON t.symbol = a.symbol AND t.ts = a.as_of
  CROSS JOIN LATERAL (
    WITH fwd AS (
      SELECT i.rn, i.cl, (i.lo <= t.stop_price) AS sl, (i.hi >= t.target_price) AS tp
      FROM _px i WHERE i.symbol = a.symbol AND i.rn > e.rn AND i.rn <= e.rn + p_maxhold
    ),
    first_hit AS (
      SELECT CASE WHEN sl THEN t.stop_price ELSE t.target_price END AS exit_price,
             CASE WHEN sl THEN 'stop' ELSE 'target' END             AS reason
      FROM fwd WHERE sl OR tp ORDER BY rn LIMIT 1
    ),
    matured AS (
      SELECT cl AS exit_price, 'timeout' AS reason
      FROM _px WHERE symbol = a.symbol AND rn = e.rn + p_maxhold
    )
    SELECT exit_price, reason FROM first_hit
    UNION ALL SELECT exit_price, reason FROM matured WHERE NOT EXISTS (SELECT 1 FROM first_hit)
    LIMIT 1
  ) x
  WHERE o.analysis_id IS NULL
    AND a.skill <> 'strat-bb-trend'
    AND a.skill <> 'strat-bb-breakout';   -- 兩者皆走「跌破20MA」專屬評分，不混 bracket
  GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
END $$;
GRANT EXECUTE ON FUNCTION evaluate_due_predictions(INT, NUMERIC) TO stock_app;
