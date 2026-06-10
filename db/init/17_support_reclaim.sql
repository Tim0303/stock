-- 17_support_reclaim.sql — 破支撐拉回 / 假跌破收復（Wyckoff spring）偵測（第六位分析師雛形）
-- 概念：盤整下緣（近期水平支撐）被「短暫跌破又收復」= 洗盤/假跌破，常是低風險買點。
-- 還原價一律 close*adj_factor（由 v_price_indicators 提供，前復權）。純往回窗口、無前視。
--
-- 兩種支撐：
--   sup（水平）：近 20 日(到 3 日前) 的最低 = 已建立的盤整下緣（不含最近 3 日的跌破本身）
--   ma20（均線）：跌破 20MA 後收復
--
-- spring_signal（核心）：近 3 日曾破水平支撐 + 今收重新站回支撐之上 + 收紅
-- reclaim_ma20       ：昨收破 20MA、今收站回 20MA

CREATE OR REPLACE VIEW v_support_reclaim AS
WITH base AS (
  SELECT
    symbol, ts, open, high, low, close, volume,
    ma20, ma20_prev, close_prev, n_window,
    -- 已建立的水平支撐：近 20 日(到 3 日前)最低（排除最近 3 日的跌破本身）
    min(low)  OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 22 PRECEDING AND 3 PRECEDING) AS sup,
    -- 近 3 日(含當日)最低：判斷是否「剛跌破」支撐
    min(low)  OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 2  PRECEDING AND CURRENT ROW) AS low_3d,
    -- 近 20 日區間（判斷是否真盤整、窄幅）
    max(high) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS hi_20,
    min(low)  OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS lo_20,
    avg(volume) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) AS vol_ma50,
    -- 上方壓力：前 60 日最高（不含當日）→ 出場目標用
    max(high) OVER (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING) AS res60
  FROM v_price_indicators
  WHERE n_window >= 20
),
calc AS (
  SELECT
    symbol, ts, open, high, low, close, volume, ma20, ma20_prev, sup, res60,
    round(((close / NULLIF(sup,0)) - 1) * 100, 2)                              AS above_sup_pct,
    CASE WHEN lo_20 > 0 THEN round(((hi_20 - lo_20) / lo_20) * 100, 1) END     AS range20_pct,
    CASE WHEN vol_ma50 > 0 THEN round((volume / vol_ma50)::numeric, 2) END     AS vol_ratio,
    CASE WHEN (high - low) > 0
         THEN round(((close - open) / (high - low))::numeric, 2) END           AS body_ratio,
    -- 核心：假跌破收復（spring）
    (low_3d < sup AND close > sup AND close > close_prev)                      AS spring_signal,
    -- 破 20MA 後收復
    (close_prev < ma20_prev AND close > ma20 AND close > close_prev)           AS reclaim_ma20
  FROM base
)
SELECT
  symbol, ts, open, high, low, close, volume, ma20, sup,
  above_sup_pct, range20_pct, vol_ratio, body_ratio,
  spring_signal, reclaim_ma20,
  -- 0-100 分：核心 + 真盤整(窄幅) + 收紅力道 + 深度量縮(Wyckoff spring 賣壓枯竭) + 貼著支撐
  -- 註(2026-06-10 特徵回測)：spring 量縮<0.7 PF1.80 遠勝放量1.13 → 改獎勵量縮、非放量。
  ( CASE WHEN spring_signal THEN 50 ELSE 0 END
  + CASE WHEN range20_pct IS NOT NULL AND range20_pct <= 18 THEN 15 ELSE 0 END
  + CASE WHEN body_ratio IS NOT NULL THEN round(15 * greatest(0, least(1, body_ratio))) ELSE 0 END
  + CASE WHEN vol_ratio IS NOT NULL AND vol_ratio < 0.7 THEN 10 ELSE 0 END
  + CASE WHEN above_sup_pct IS NOT NULL AND above_sup_pct BETWEEN 0 AND 3 THEN 10 ELSE 0 END
  )::int                                                                       AS score,
  CASE
    -- spring 只認「上升趨勢中的假跌破收復」：站上 20MA 且 20MA 上彎（回測 PF≈1.70）；
    -- 逆勢(20MA下)的破底反彈是 falling knife（PF≈0.70），不發訊號。
    -- 量縮優先(vol_ratio<1.0)：Wyckoff spring 須賣壓枯竭；放量跌破多為真出貨（量縮版勝率65%>原60%、年度更穩）。
    WHEN spring_signal AND range20_pct IS NOT NULL AND range20_pct <= 25
         AND close > ma20 AND ma20 > ma20_prev
         AND vol_ratio < 1.0 THEN 'spring'
    WHEN reclaim_ma20 THEN 'reclaim_ma20'
    ELSE NULL
  END                                                                          AS signal_type,
  -- 交易計畫：壓力目標（上方60日前高下緣×0.99，封頂+25%；無壓力→回退+15%）+ 停損−8%
  CASE WHEN res60 > close*1.01 THEN round(LEAST(res60*0.99, close*1.25), 2)
       ELSE round(close*1.15, 2) END                                           AS target_price,
  round(close*0.92, 2)                                                         AS stop_price,
  CASE WHEN res60 > close*1.01 THEN round((LEAST(res60*0.99, close*1.25)/close - 1)*100, 1)
       ELSE 15.0 END                                                           AS target_pct
FROM calc;

-- 每檔最新一日（近期、且有訊號）— 掃描/看板用
CREATE OR REPLACE VIEW v_support_reclaim_latest AS
SELECT DISTINCT ON (symbol) *
FROM v_support_reclaim
WHERE (spring_signal OR reclaim_ma20)
  AND ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
ORDER BY symbol, ts DESC;

GRANT SELECT ON v_support_reclaim         TO stock_app, stock_readonly;
GRANT SELECT ON v_support_reclaim_latest  TO stock_app, stock_readonly;

-- ── 第六位分析師 strat-spring：種子 champion + 記錄函式 ──────────────────────
-- OOS 驗證(2026-06-09)：上升段spring PF 1.70(in-sample)、後半1.50、9/11年>1、294檔不集中。
-- 弱點：大空頭(2022 PF 0.33)，待加大盤過濾。
INSERT INTO skills (family, version, status, market_scope, params, param_hash, created_by, notes)
VALUES (
  'strat-spring', 1, 'champion', 'ALL',
  jsonb_build_object(
    'sup_lookback', 20, 'break_window', 3, 'range_max', 0.25,
    'trend_gate', 'close>ma20 AND ma20 rising', 'horizon_days', 5,
    'enter_threshold', 60
  ),
  'seed-spring-v1', 'system', '破支撐拉回(Wyckoff spring)：上升段假跌破收復。OOS 後半 PF 1.50。'
)
ON CONFLICT (family, version) DO NOTHING;

-- 記錄當日 spring 訊號 → analyses（live、防重、entry=還原收盤、due=as_of+7）
CREATE OR REPLACE FUNCTION record_spring_signals(p_horizon INT DEFAULT NULL)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
  n INT;
  v_skill_id BIGINT;
  v_h INT;
BEGIN
  SELECT skill_id INTO v_skill_id FROM skills
  WHERE family='strat-spring' AND status='champion' ORDER BY version DESC LIMIT 1;
  v_h := COALESCE(p_horizon, 5);

  INSERT INTO analyses
    (symbol, skill, skill_id, as_of, horizon_days, due_date,
     direction, predicted, score, signal_type, entry_price, meta)
  SELECT
    r.symbol, 'strat-spring', v_skill_id, r.ts, v_h,
    r.ts + make_interval(days => CEIL(v_h * 1.4)::int),
    'long', 'up', r.score, 'spring', r.close,
    jsonb_build_object('sup', round(r.sup,2), 'above_sup_pct', r.above_sup_pct,
                       'range20_pct', r.range20_pct, 'body_ratio', r.body_ratio)
  FROM v_support_reclaim_latest r
  WHERE r.signal_type = 'spring'
    AND r.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
    -- 大盤過濾改為「僅提示」：弱市照樣開倉，看板 badge 提醒風險（使用者 2026-06-10 定案）
    AND NOT EXISTS (
      SELECT 1 FROM analyses a
      WHERE a.symbol = r.symbol AND a.skill='strat-spring' AND a.as_of = r.ts
    );
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;

GRANT EXECUTE ON FUNCTION record_spring_signals(INT) TO stock_app;
