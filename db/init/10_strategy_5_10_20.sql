-- 10_strategy_5_10_20.sql — 5-10-20 短線策略規則化（T5, analysis-sql-agent）★主幹里程碑
-- 來源：5-10-20短線順勢進出訊號策略.md（進場 A/B/C、分數模型第22節、過濾、評級）。
-- 吃當前 champion 技能的參數（權重/門檻），算 0-100 分與進場訊號；
-- record_strategy_signals() 把 buy 訊號寫進 analyses → 走評分迴路。

CREATE OR REPLACE VIEW v_strategy_5_10_20 AS
WITH champ AS (
  SELECT skill_id, params FROM skills
  WHERE family = 'strat-5-10-20' AND status = 'champion'
  ORDER BY version DESC LIMIT 1
),
p AS (
  SELECT
    skill_id,
    (params->>'w_bull_align')::numeric      AS w_bull,
    (params->>'w_above_ma5')::numeric       AS w_ma5,
    (params->>'w_breakout_5d_high')::numeric AS w_brk,
    (params->>'w_volume')::numeric          AS w_vol,
    (params->>'w_ma20_up')::numeric         AS w_ma20up,
    (params->>'enter_threshold')::numeric   AS enter_thr,
    (params->>'watch_threshold')::numeric   AS watch_thr,
    (params->>'bias_ma20_max')::numeric     AS bias20max,
    (params->>'bias_ma10_max')::numeric     AS bias10max,
    COALESCE((params->>'vol_ratio_min')::numeric, 1.0)    AS volmin,
    COALESCE((params->>'pullback_vol_cap')::numeric, 1.5) AS pbvolcap,
    COALESCE((params->>'enable_signal_A')::boolean, true) AS en_a,
    COALESCE((params->>'enable_signal_B')::boolean, true) AS en_b,
    COALESCE((params->>'enable_signal_C')::boolean, true) AS en_c,
    -- 防追高：A 突破只在「突破點(前5日高)上方 brk_max_ext 內」才買；預設 99=不限制（champion 行為不變）
    COALESCE((params->>'breakout_max_ext')::numeric, 99)  AS brk_max_ext,
    COALESCE((params->>'horizon_days')::int, 5)           AS horizon
  FROM champ
),
calc AS (
  SELECT
    i.symbol, i.ts, i.open, i.high, i.low, i.close, i.volume,
    i.ma5, i.ma10, i.ma20, i.vol_ma5, i.prev_high_5,
    i.bias_ma10, i.bias_ma20, i.ma20_prev, i.ma5_prev, i.close_prev,
    p.*,
    -- 多方結構：Close>5MA>10MA>20MA 且 20MA 走平或上彎
    (i.close > i.ma5 AND i.ma5 > i.ma10 AND i.ma10 > i.ma20
       AND i.ma20 >= i.ma20_prev)                                   AS bull_align,
    -- 進場 A 突破：多方 + 突破前5日高 + 放量 + 防追高（收盤須在突破點上方 brk_max_ext 內）
    (p.en_a AND i.close > i.ma5 AND i.ma5 > i.ma10 AND i.ma10 > i.ma20
       AND i.close > i.prev_high_5
       AND i.close <= i.prev_high_5 * (1 + p.brk_max_ext)
       AND i.volume > i.vol_ma5 * p.volmin) AS sig_a,
    -- 進場 B 回測10MA不破：多方排列 + 探10MA未破 + 收紅 + 未爆量
    (p.en_b AND i.ma5 > i.ma10 AND i.ma10 > i.ma20
       AND i.low <= i.ma10 AND i.close > i.ma10
       AND i.close > i.close_prev AND i.volume <= i.vol_ma5 * p.pbvolcap) AS sig_b,
    -- 進場 C 站回5MA：昨破5MA今站回 + 多方 + 收紅
    (p.en_c AND i.close_prev < i.ma5_prev AND i.close > i.ma5
       AND i.ma5 > i.ma10 AND i.ma10 >= i.ma20 AND i.close > i.close_prev) AS sig_c,
    -- 過濾（即使分數高也不進場）：跌破20MA / 乖離過大 / 20MA下彎
    (i.close < i.ma20 OR i.bias_ma20 > p.bias20max
       OR i.bias_ma10 > p.bias10max OR i.ma20 < i.ma20_prev)        AS filtered,
    i.n_window,
    -- 上方壓力：前 60 日最高（不含當日）→ 出場目標用
    max(i.high) OVER (PARTITION BY i.symbol ORDER BY i.ts
                      ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)     AS prev_high_60
  FROM v_price_indicators i CROSS JOIN p
)
SELECT
  symbol, ts, open, high, low, close, volume, ma5, ma10, ma20, vol_ma5,
  prev_high_5, bias_ma10, bias_ma20, bull_align, sig_a, sig_b, sig_c, filtered,
  skill_id, horizon AS horizon_days,
  -- 分數模型（文件第22節）：各項用 champion 權重
  ( CASE WHEN bull_align                       THEN w_bull   ELSE 0 END
  + CASE WHEN close > ma5                       THEN w_ma5    ELSE 0 END
  + CASE WHEN close > prev_high_5               THEN w_brk    ELSE 0 END
  + CASE WHEN volume > vol_ma5 * volmin         THEN w_vol    ELSE 0 END
  + CASE WHEN ma20 > ma20_prev                  THEN w_ma20up ELSE 0 END
  )::numeric AS score,
  CASE WHEN sig_a THEN 'A' WHEN sig_b THEN 'B' WHEN sig_c THEN 'C' END AS signal_type,
  CASE
    WHEN filtered THEN 'avoid'
    WHEN (sig_a OR sig_b OR sig_c)   -- 進場品質：必須觸發真 A/B/C 訊號（非僅結構強）
         AND ( CASE WHEN bull_align THEN w_bull ELSE 0 END
         + CASE WHEN close > ma5 THEN w_ma5 ELSE 0 END
         + CASE WHEN close > prev_high_5 THEN w_brk ELSE 0 END
         + CASE WHEN volume > vol_ma5 * volmin THEN w_vol ELSE 0 END
         + CASE WHEN ma20 > ma20_prev THEN w_ma20up ELSE 0 END ) >= enter_thr THEN 'buy'
    WHEN ( CASE WHEN bull_align THEN w_bull ELSE 0 END
         + CASE WHEN close > ma5 THEN w_ma5 ELSE 0 END
         + CASE WHEN close > prev_high_5 THEN w_brk ELSE 0 END
         + CASE WHEN volume > vol_ma5 * volmin THEN w_vol ELSE 0 END
         + CASE WHEN ma20 > ma20_prev THEN w_ma20up ELSE 0 END ) >= watch_thr THEN 'watch'
    ELSE 'skip'
  END AS rating,
  -- 交易計畫：壓力目標（上方60日前高下緣×0.99，封頂+25%；無壓力→回退+15%）+ 停損−8%
  CASE WHEN prev_high_60 > close*1.01 THEN round(LEAST(prev_high_60*0.99, close*1.25), 2)
       ELSE round(close*1.15, 2) END                                   AS target_price,
  round(close*0.92, 2)                                                 AS stop_price,
  CASE WHEN prev_high_60 > close*1.01 THEN round((LEAST(prev_high_60*0.99, close*1.25)/close - 1)*100, 1)
       ELSE 15.0 END                                                   AS target_pct
FROM calc
WHERE n_window >= 20;   -- 需至少 20 日資料，20MA 才完整

-- 每檔最新一日（掃描/推送用）
CREATE OR REPLACE VIEW v_strategy_latest AS
SELECT DISTINCT ON (symbol) *
FROM v_strategy_5_10_20
ORDER BY symbol, ts DESC;

-- ── 把最新 buy 訊號寫進 analyses → 進評分迴路 ────────────────────────────
-- due_date：horizon 個交易日後（用日曆近似 ×1.4，評分函式取 due_date 當天/之後第一個交易日）
CREATE OR REPLACE FUNCTION record_strategy_signals(p_horizon INT DEFAULT NULL)
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
  n INT;
BEGIN
  INSERT INTO analyses
    (symbol, skill, skill_id, as_of, horizon_days, due_date,
     direction, predicted, score, signal_type, entry_price)
  SELECT
    l.symbol, 'strat-5-10-20', l.skill_id, l.ts,
    COALESCE(p_horizon, l.horizon_days),
    l.ts + make_interval(days => CEIL(COALESCE(p_horizon, l.horizon_days) * 1.4)::int),
    'long', 'up', l.score, l.signal_type, l.close
  FROM v_strategy_latest l
  WHERE l.rating = 'buy'
    -- 只收「近期仍在交易」的真實當前訊號，排除下市/停止交易的殭屍股
    -- （它們的最新資料停在數年前，due_date 早過，不該當即時預測）
    AND l.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
    -- 大盤過濾改為「僅提示」：弱市(寬度<50%)照樣開倉，看板 badge 提醒風險（使用者 2026-06-10 定案）
    AND NOT EXISTS (
      SELECT 1 FROM analyses a
      WHERE a.symbol = l.symbol AND a.skill = 'strat-5-10-20' AND a.as_of = l.ts
    );
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;
