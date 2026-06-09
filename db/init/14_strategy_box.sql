-- 14_strategy_box.sql — 箱型區間策略 strat-box（第四個分析師，box-agent）
-- 來源：箱型區間策略.md（兩段式箱型偵測、箱底止跌買、箱頂保守賣、跌破箱底停損、0-100 評分）。
-- 鐵律：所有價格用還原權值（OHLC × adj_factor），與 strat-5-10-20 一致；量不調整。
-- 使用者拍板：箱底至少觸碰 2 次、箱頂保守出（碰箱頂就出）、N=60/W=15%/k=3/停損 3%。
--
-- 物件：
--   v_box_swings           ：每日還原 OHLC + swing 高/低（前後 k 日局部極值）
--   v_box_indicators       ：box_high/low/height + box_low_tests/box_high_tests
--                            + 止跌訊號 + 箱內位置
--   v_strategy_box         ：方法1+方法2 → is_real_box；箱底買訊號；0-100 分；rating
--   v_strategy_box_latest  ：每檔最新一日
--   record_box_signals()   ：把箱底 buy 訊號寫進 analyses（近期過濾、防重）
--   box_backtest_trades / run_box_backtest() / v_box_backtest：box 專用出場回測
--   種子 strat-box champion skill（family='strat-box', version=1, champion）

-- ════════════════════════════════════════════════════════════════════════
-- 種子 strat-box champion（先建，view 需吃其參數）
-- ════════════════════════════════════════════════════════════════════════
INSERT INTO skills (family, version, status, market_scope, params, param_hash, created_by, notes)
VALUES (
  'strat-box', 1, 'champion', 'ALL',
  jsonb_build_object(
    'N', 60,                    -- 箱型回溯窗口（約 3 個月）
    'W', 0.15,                  -- 最大箱寬（box_height/box_low <= 15%）
    'k', 3,                     -- swing 敏感度（前後各 k 日局部極值）
    'box_low_tests_min', 2,     -- 箱底最少觸碰（使用者拍板）
    'box_high_tests_min', 2,    -- 箱頂最少觸碰
    'box_zone_ratio', 0.25,     -- 上下緣各 1/4 為進出區
    'test_band_ratio', 0.10,    -- swing 落在箱界 ±box_height×10% 視為一次測試
    'slope_eps', 0.0015,        -- 橫向：標準化日斜率絕對值門檻
    'stop_loss_pct', 0.03,      -- 跌破 box_low×0.97 停損
    'breakout_vol_mult', 1.5,   -- 帶量突破判定
    'w_real_box', 40,           -- 評分：箱型有效
    'w_position', 20,           -- 評分：越靠箱底
    'w_stop_falling', 20,       -- 評分：止跌訊號強度
    'w_low_tests', 10,          -- 評分：箱底測試次數
    'w_market', 10,             -- 評分：大盤未轉弱（暫常給滿）
    'enter_threshold', 80,      -- >=80 買進候選
    'watch_threshold', 60,      -- 60~79 觀察
    'horizon_days', 5
  ),
  'seed-box-v1', 'system', '箱型區間策略文件預設參數（冠軍基準，演化前凍結）'
)
ON CONFLICT (family, version) DO NOTHING;

-- ════════════════════════════════════════════════════════════════════════
-- 1) v_box_swings — 還原 OHLC + swing 高/低點（前後各 k 日的局部極值）
-- ════════════════════════════════════════════════════════════════════════
-- 註：swing 窗口 k 須為常數（Postgres 窗口框 ROWS 不接受變數）。
-- champion k 預設 3；若要演化 k，改本 view 的 ROWS 偏移即可（同 N 視窗的箱界用 N=60 同理見下）。
CREATE OR REPLACE VIEW v_box_swings AS
WITH adj AS (   -- 還原權值 OHLC（量不調整）
  SELECT symbol, ts, volume,
    open  * adj_factor AS open,
    high  * adj_factor AS high,
    low   * adj_factor AS low,
    close * adj_factor AS close
  FROM daily_prices
)
SELECT
  a.symbol, a.ts, a.open, a.high, a.low, a.close, a.volume,
  3 AS k_swing,
  -- swing high：當日 high 為前後各 3 日窗口最高；swing low 同理
  (a.high = max(a.high) OVER wK) AS is_swing_high,
  (a.low  = min(a.low)  OVER wK) AS is_swing_low,
  lag(a.close)  OVER ph AS close_prev,
  lag(a.volume) OVER ph AS vol_prev,
  avg(a.volume) OVER w5p AS vol_ma5_prev
FROM adj a
WINDOW
  wK  AS (PARTITION BY a.symbol ORDER BY a.ts
          ROWS BETWEEN 3 PRECEDING AND 3 FOLLOWING),
  w5p AS (PARTITION BY a.symbol ORDER BY a.ts ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING),
  ph  AS (PARTITION BY a.symbol ORDER BY a.ts);

-- ════════════════════════════════════════════════════════════════════════
-- 2) v_box_indicators — 箱界、測試次數、止跌訊號、位置、橫向
-- ════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE VIEW v_box_indicators AS
WITH champ AS (
  SELECT
    COALESCE((params->>'N')::int, 60)                    AS n_win,
    COALESCE((params->>'W')::numeric, 0.15)              AS w_max,
    COALESCE((params->>'k')::int, 3)                     AS k_swing,
    COALESCE((params->>'box_zone_ratio')::numeric, 0.25) AS zone_ratio,
    COALESCE((params->>'test_band_ratio')::numeric, 0.10) AS band_ratio,
    COALESCE((params->>'slope_eps')::numeric, 0.0015)    AS slope_eps,
    COALESCE((params->>'breakout_vol_mult')::numeric, 1.5) AS brk_vol
  FROM skills WHERE family = 'strat-box' AND status = 'champion'
  ORDER BY version DESC LIMIT 1
),
box AS (   -- 箱界（近 N 日含當日）、橫向斜率、量能、行序號
  SELECT
    s.symbol, s.ts, s.open, s.high, s.low, s.close, s.volume,
    s.close_prev, s.vol_prev, s.vol_ma5_prev, s.is_swing_high, s.is_swing_low,
    c.n_win, c.w_max, c.zone_ratio, c.band_ratio, c.slope_eps, c.brk_vol,
    max(s.high) OVER wN AS box_high,
    min(s.low)  OVER wN AS box_low,
    count(*)    OVER wN AS n_window,
    regr_slope(s.close, extract(epoch FROM s.ts)/86400.0) OVER wN AS slope_raw,
    row_number() OVER (PARTITION BY s.symbol ORDER BY s.ts) AS rn
  FROM v_box_swings s CROSS JOIN champ c
  -- N=60 窗口；ROWS 偏移須常數（59 PRECEDING = 含當日共 60 日）
  WINDOW wN AS (PARTITION BY s.symbol ORDER BY s.ts
                ROWS BETWEEN 59 PRECEDING AND CURRENT ROW)
),
-- swing 點清單（含行序號），供測試次數自連接
sw AS (
  SELECT symbol, ts, high, low, is_swing_high, is_swing_low,
         row_number() OVER (PARTITION BY symbol ORDER BY ts) AS rn
  FROM v_box_swings
),
-- 測試次數：對每個 box 列，數其近 N 日窗口（rn-N+1..rn）內，落在箱界 ±box_height×band 的 swing 點
tests AS (
  SELECT b.symbol, b.ts,
    count(*) FILTER (
      WHERE sw.is_swing_low
        AND abs(sw.low - b.box_low) <= (b.box_high - b.box_low) * b.band_ratio
    ) AS box_low_tests,
    count(*) FILTER (
      WHERE sw.is_swing_high
        AND abs(sw.high - b.box_high) <= (b.box_high - b.box_low) * b.band_ratio
    ) AS box_high_tests
  FROM box b
  JOIN sw ON sw.symbol = b.symbol
        -- 上界 b.rn-3：排除最近 3 日「尚未確認」的 swing（其前後 k=3 日還沒到齊）→ 消除前視偏差
        AND sw.rn BETWEEN b.rn - b.n_win + 1 AND b.rn - 3
  GROUP BY b.symbol, b.ts
)
SELECT
  b.symbol, b.ts, b.open, b.high, b.low, b.close, b.volume,
  b.box_high, b.box_low,
  (b.box_high - b.box_low)                                   AS box_height,
  (b.box_high + b.box_low) / 2.0                             AS box_mid,
  b.n_window, b.n_win, b.w_max, b.zone_ratio, b.band_ratio, b.slope_eps, b.brk_vol,
  b.close_prev, b.vol_prev, b.vol_ma5_prev,
  COALESCE(t.box_low_tests, 0)                              AS box_low_tests,
  COALESCE(t.box_high_tests, 0)                             AS box_high_tests,
  -- 方法1 粗篩量：箱寬比、標準化斜率
  CASE WHEN b.box_low > 0 THEN (b.box_high - b.box_low) / b.box_low END AS box_width_ratio,
  CASE WHEN (b.box_high + b.box_low) > 0
       THEN b.slope_raw / ((b.box_high + b.box_low) / 2.0) END          AS slope_norm,
  -- 箱內位置（0=箱底 1=箱頂）
  CASE WHEN (b.box_high - b.box_low) > 0
       THEN (b.close - b.box_low) / (b.box_high - b.box_low) END        AS box_pos,
  -- ── 止跌訊號（四項，箱型策略.md 第4節）──
  -- 1) 長下影：(min(open,close)-low)/(high-low) > 0.5
  CASE WHEN (b.high - b.low) > 0
       THEN (least(b.open, b.close) - b.low) / (b.high - b.low) > 0.5
       ELSE false END                                                   AS sig_lower_shadow,
  -- 2) 十字星：|close-open|/(high-low) < 0.1
  CASE WHEN (b.high - b.low) > 0
       THEN abs(b.close - b.open) / (b.high - b.low) < 0.1
       ELSE false END                                                   AS sig_doji,
  -- 3) 量縮後放大：前一日量 < 5日均量(不含當日) 且 當日量 > 前一日量×1.3
  (b.vol_prev IS NOT NULL AND b.vol_ma5_prev IS NOT NULL
     AND b.vol_prev < b.vol_ma5_prev
     AND b.volume > b.vol_prev * 1.3)                                   AS sig_vol_expand,
  -- 4) 收紅止跌：close > 前一日 close
  (b.close_prev IS NOT NULL AND b.close > b.close_prev)                 AS sig_close_up,
  -- 帶量突破箱頂（失效）：close > box_high 且 量 > 5日均量×brk_vol
  (b.close > b.box_high AND b.vol_ma5_prev IS NOT NULL
     AND b.volume > b.vol_ma5_prev * b.brk_vol)                         AS breakout_up
FROM box b
LEFT JOIN tests t ON t.symbol = b.symbol AND t.ts = b.ts;

-- ════════════════════════════════════════════════════════════════════════
-- 3) v_strategy_box — 真箱型判定 + 箱底買訊號 + 0-100 分 + 評級
-- ════════════════════════════════════════════════════════════════════════
-- 需至少 N 日資料（box 才完整）；小函式回傳 champion N 供 view WHERE 使用
CREATE OR REPLACE FUNCTION n_win_floor() RETURNS int
LANGUAGE sql STABLE AS $$
  SELECT COALESCE((params->>'N')::int, 60)
  FROM skills WHERE family='strat-box' AND status='champion'
  ORDER BY version DESC LIMIT 1;
$$;

CREATE OR REPLACE VIEW v_strategy_box AS
WITH champ AS (
  SELECT skill_id,
    COALESCE((params->>'box_low_tests_min')::int, 2)  AS lo_min,
    COALESCE((params->>'box_high_tests_min')::int, 2) AS hi_min,
    COALESCE((params->>'w_real_box')::numeric, 40)    AS w_box,
    COALESCE((params->>'w_position')::numeric, 20)    AS w_pos,
    COALESCE((params->>'w_stop_falling')::numeric, 20) AS w_stop,
    COALESCE((params->>'w_low_tests')::numeric, 10)   AS w_lo,
    COALESCE((params->>'w_market')::numeric, 10)      AS w_mkt,
    COALESCE((params->>'enter_threshold')::numeric, 80) AS enter_thr,
    COALESCE((params->>'watch_threshold')::numeric, 60) AS watch_thr,
    COALESCE((params->>'horizon_days')::int, 5)       AS horizon
  FROM skills WHERE family = 'strat-box' AND status = 'champion'
  ORDER BY version DESC LIMIT 1
),
calc AS (
  SELECT
    i.*, p.skill_id, p.lo_min, p.hi_min, p.horizon,
    p.w_box, p.w_pos, p.w_stop, p.w_lo, p.w_mkt, p.enter_thr, p.watch_thr,
    -- 方法1：箱寬 <= W 且 橫向（|slope_norm| < eps）
    (i.box_width_ratio IS NOT NULL AND i.box_width_ratio <= i.w_max
       AND i.slope_norm IS NOT NULL AND abs(i.slope_norm) < i.slope_eps) AS is_box_shape,
    -- 方法2：箱底/箱頂測試次數達標
    (i.box_low_tests >= p.lo_min AND i.box_high_tests >= p.hi_min)       AS tests_ok,
    -- 止跌訊號數（0~4）
    ( (i.sig_lower_shadow)::int + (i.sig_doji)::int
      + (i.sig_vol_expand)::int + (i.sig_close_up)::int )                AS n_stop_signals,
    -- 箱底 1/4 區
    (i.box_pos IS NOT NULL AND i.box_pos < i.zone_ratio)                AS at_box_bottom,
    -- 箱頂 1/4 區
    (i.box_pos IS NOT NULL AND i.box_pos > (1 - i.zone_ratio))          AS at_box_top
  FROM v_box_indicators i CROSS JOIN champ p
)
SELECT
  symbol, ts, open, high, low, close, volume,
  box_high, box_low, box_height, box_mid, box_pos, n_window,
  box_low_tests, box_high_tests, box_width_ratio, slope_norm,
  sig_lower_shadow, sig_doji, sig_vol_expand, sig_close_up, n_stop_signals,
  breakout_up, is_box_shape, tests_ok, at_box_bottom, at_box_top,
  skill_id, horizon AS horizon_days,
  -- 真箱型
  (is_box_shape AND tests_ok) AS is_real_box,
  -- 箱底買訊號：真箱型 + 箱底1/4 + 至少一個止跌訊號 + 非帶量突破
  (is_box_shape AND tests_ok AND at_box_bottom
     AND n_stop_signals >= 1 AND NOT breakout_up)                       AS buy_signal,
  -- ── 0-100 評分（文件第9節）──
  ( CASE WHEN (is_box_shape AND tests_ok) THEN w_box ELSE 0 END
    -- 位置：越靠箱底越高（1-box_pos 線性，僅在箱內計）
    + CASE WHEN box_pos IS NOT NULL
           THEN w_pos * greatest(0, least(1, 1 - box_pos)) ELSE 0 END
    -- 止跌強度：每個訊號佔 w_stop/2，封頂 w_stop
    + least(w_stop, n_stop_signals * (w_stop / 2.0))
    -- 箱底測試次數：每多一次 +w_lo/2，封頂 w_lo（2 次給滿一半，3+ 給滿）
    + least(w_lo, greatest(0, box_low_tests - 1) * (w_lo / 2.0))
    -- 大盤未轉弱（大盤判定後續接，先給滿）
    + w_mkt
  )::numeric AS score,
  CASE WHEN sig_lower_shadow THEN 'shadow'
       WHEN sig_vol_expand   THEN 'vol'
       WHEN sig_doji         THEN 'doji'
       WHEN sig_close_up     THEN 'up' END                              AS signal_type,
  CASE
    WHEN (is_box_shape AND tests_ok AND at_box_bottom
          AND n_stop_signals >= 1 AND NOT breakout_up)
         AND ( CASE WHEN (is_box_shape AND tests_ok) THEN w_box ELSE 0 END
             + CASE WHEN box_pos IS NOT NULL THEN w_pos*greatest(0,least(1,1-box_pos)) ELSE 0 END
             + least(w_stop, n_stop_signals*(w_stop/2.0))
             + least(w_lo, greatest(0, box_low_tests-1)*(w_lo/2.0))
             + w_mkt ) >= enter_thr THEN 'buy'
    WHEN (is_box_shape AND tests_ok)
         AND ( CASE WHEN (is_box_shape AND tests_ok) THEN w_box ELSE 0 END
             + CASE WHEN box_pos IS NOT NULL THEN w_pos*greatest(0,least(1,1-box_pos)) ELSE 0 END
             + least(w_stop, n_stop_signals*(w_stop/2.0))
             + least(w_lo, greatest(0, box_low_tests-1)*(w_lo/2.0))
             + w_mkt ) >= watch_thr THEN 'watch'
    ELSE 'skip'
  END AS rating
FROM calc
WHERE n_window >= n_win_floor()
;

-- 每檔最新一日（掃描/推送用）
CREATE OR REPLACE VIEW v_strategy_box_latest AS
SELECT DISTINCT ON (symbol) *
FROM v_strategy_box
ORDER BY symbol, ts DESC;

-- ════════════════════════════════════════════════════════════════════════
-- 4) record_box_signals — 把箱底 buy 訊號寫進 analyses（近期過濾、防重）
--    due_date = as_of + 7 日曆日（與其他分析師對齊）
-- ════════════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION record_box_signals(p_horizon INT DEFAULT NULL)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
  n INT;
BEGIN
  INSERT INTO analyses
    (symbol, skill, skill_id, as_of, horizon_days, due_date,
     direction, predicted, score, signal_type, entry_price, meta)
  SELECT
    l.symbol, 'strat-box', l.skill_id, l.ts,
    COALESCE(p_horizon, l.horizon_days),
    l.ts + INTERVAL '7 days',
    'long', 'up', l.score, l.signal_type, l.close,
    jsonb_build_object(
      'box_high', round(l.box_high, 2), 'box_low', round(l.box_low, 2),
      'box_pos', round(l.box_pos, 3),
      'box_low_tests', l.box_low_tests, 'box_high_tests', l.box_high_tests,
      'n_stop_signals', l.n_stop_signals
    )
  FROM v_strategy_box_latest l
  WHERE l.rating = 'buy'
    AND l.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
    AND NOT EXISTS (
      SELECT 1 FROM analyses a
      WHERE a.symbol = l.symbol AND a.skill = 'strat-box' AND a.as_of = l.ts
    );
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;

-- ════════════════════════════════════════════════════════════════════════
-- 5) box 專用回測：碰箱頂1/4出（獲利了結）或 跌破 box_low×0.97（停損）即出
-- ════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS box_backtest_trades (
  symbol      text,
  entry_date  date,
  entry_price numeric,
  exit_date   date,
  exit_price  numeric,
  exit_reason text,        -- hit_top / stop_loss
  gross_ret   numeric,
  net_ret     numeric,
  hold_days   int
);

CREATE OR REPLACE FUNCTION run_box_backtest(
  stop_loss_pct numeric DEFAULT 0.03,
  txn_cost      numeric DEFAULT 0.006
)
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
  n int;
BEGIN
  TRUNCATE box_backtest_trades;

  -- 物化回測所需欄位（view 重算窗口太慢）
  CREATE TEMP TABLE _bi ON COMMIT DROP AS
    SELECT symbol, ts, close, box_high, box_low, box_height, box_pos
    FROM v_strategy_box;
  CREATE INDEX ON _bi (symbol, ts);

  INSERT INTO box_backtest_trades
  SELECT
    e.symbol, e.entry_date, e.entry_price,
    x.exit_date, x.exit_price, x.exit_reason,
    round((x.exit_price - e.entry_price) / e.entry_price, 5)            AS gross_ret,
    round((x.exit_price - e.entry_price) / e.entry_price - txn_cost, 5) AS net_ret,
    (x.exit_date - e.entry_date)                                       AS hold_days
  FROM (
    SELECT symbol, ts AS entry_date, close AS entry_price, box_low AS entry_box_low
    FROM v_strategy_box
    WHERE buy_signal
  ) e
  CROSS JOIN LATERAL (
    SELECT i.ts AS exit_date, i.close AS exit_price,
      CASE WHEN i.close <= e.entry_box_low * (1 - stop_loss_pct) THEN 'stop_loss'
           ELSE 'hit_top' END AS exit_reason
    FROM _bi i
    WHERE i.symbol = e.symbol AND i.ts > e.entry_date
      AND (
        -- 碰箱頂 1/4 區（用進場當下的 box_low 與當前 box_high 算位置；保守用 box_pos）
        i.box_pos > 0.75
        OR i.close <= e.entry_box_low * (1 - stop_loss_pct)
      )
    ORDER BY i.ts
    LIMIT 1
  ) x;

  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;

CREATE OR REPLACE VIEW v_box_backtest AS
SELECT
  count(*)                                                              AS n_trades,
  round(avg((net_ret > 0)::int), 3)                                     AS win_rate,
  round(avg(net_ret), 4)                                                AS avg_net_ret,
  round(sum(net_ret) FILTER (WHERE net_ret > 0)
        / NULLIF(abs(sum(net_ret) FILTER (WHERE net_ret < 0)), 0), 3)   AS profit_factor,
  round(avg(hold_days), 1)                                              AS avg_hold_days,
  count(*) FILTER (WHERE exit_reason = 'stop_loss')                     AS n_stop_loss,
  count(*) FILTER (WHERE exit_reason = 'hit_top')                       AS n_hit_top,
  round(max(net_ret), 3)                                                AS best,
  round(min(net_ret), 3)                                                AS worst
FROM box_backtest_trades;
