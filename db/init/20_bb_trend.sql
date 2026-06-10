-- 20_bb_trend.sql — 布林通道趨勢續抱策略 strat-bb-trend（分析師）
-- 進場 = 5-10-20 買訊（同 v_strategy_latest rating='buy'，沿用其 A/C 訊號與分數）。
-- 出場 = 趨勢續抱（BB 中軌觀念）：收盤站上 20MA 續抱（沿軌道、含咬上軌強勢段），
--        收盤跌破 20MA 才停利出場、或 −8% 停損。★無時間上限（不設 maxhold，讓利潤奔跑到趨勢結束）。
-- 與 strat-5-10-20 共用進場、差在出場 → 換取大波段，但報酬集中少數肥尾單、勝率低、變異大。
-- ★ 評分不混用 bracket：見 evaluate_bb_trend()（跌破20MA/−8%，無到期）；主 evaluate 已排除本 skill。
-- 註：尚未跌破20MA也未停損的「仍持有中」預測，維持未評分（留待真正出場才結算）。

INSERT INTO skills (family, version, status, market_scope, params, param_hash, created_by, notes)
VALUES ('strat-bb-trend', 1, 'champion', 'ALL',
  jsonb_build_object('entry','strat-5-10-20 buy','exit','trail_ma20',
                     'stop_pct',0.08,'maxhold','none','horizon_days',5),
  'seed-bbtrend-v1','human',
  '布林通道趨勢續抱：5-10-20進場 + 跌破20MA停利(無時間上限，讓利潤奔跑)+−8%停損。報酬高但集中少數大波段、勝率低、變異大。')
ON CONFLICT (family, version) DO NOTHING;
-- 既有 v1 若已存在，更新其 params/notes（移除 maxhold 限制）
UPDATE skills SET
  params = jsonb_build_object('entry','strat-5-10-20 buy','exit','trail_ma20','stop_pct',0.08,'maxhold','none','horizon_days',5),
  notes  = '布林通道趨勢續抱：5-10-20進場 + 跌破20MA停利(無時間上限，讓利潤奔跑)+−8%停損。報酬高但集中少數大波段、勝率低、變異大。'
WHERE family='strat-bb-trend' AND version=1;

-- 最新買訊（同 5-10-20 buy）+ 趨勢續抱交易計畫（停損 −8%、出場=跌破20MA、無固定獲利目標、無時間上限）
CREATE OR REPLACE VIEW v_bb_trend_latest AS
SELECT symbol, ts, score, signal_type, close AS entry_price,
       round(close*0.92, 2) AS stop_price, '跌破20MA 停利' AS exit_rule
FROM v_strategy_latest
WHERE rating = 'buy';
GRANT SELECT ON v_bb_trend_latest TO stock_app, stock_readonly;

-- 記錄：把當日 5-10-20 買訊寫進 analyses（skill=strat-bb-trend，meta 標 exit_type=trail_ma20）
CREATE OR REPLACE FUNCTION record_bb_trend_signals()
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE n INT; v_skill_id BIGINT;
BEGIN
  SELECT skill_id INTO v_skill_id FROM skills
  WHERE family='strat-bb-trend' AND status='champion' ORDER BY version DESC LIMIT 1;
  INSERT INTO analyses
    (symbol, skill, skill_id, as_of, horizon_days, due_date,
     direction, predicted, score, signal_type, entry_price, meta)
  SELECT l.symbol, 'strat-bb-trend', v_skill_id, l.ts, 5,
    l.ts + make_interval(days => 365),        -- 無 maxhold，due_date 僅供參考（出場才真正結算）
    'long', 'up', l.score, l.signal_type, l.close,
    jsonb_build_object('exit_type','trail_ma20','stop_pct',0.08,'maxhold','none')
  FROM v_strategy_latest l
  WHERE l.rating = 'buy'
    AND l.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
    -- 大盤過濾改為「僅提示」：弱市照樣開倉，看板 badge 提醒風險（使用者 2026-06-10 定案）
    AND NOT EXISTS (SELECT 1 FROM analyses a
      WHERE a.symbol=l.symbol AND a.skill='strat-bb-trend' AND a.as_of=l.ts);
  GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
END $$;
GRANT EXECUTE ON FUNCTION record_bb_trend_signals() TO stock_app;

-- 專屬評分：對 strat-bb-trend 未評分預測，用「跌破20MA / −8%」結算（無到期）。
-- 仍未出場者不產生列 → 維持未評分（留待真正跌破/停損才結算）。p_scan 僅為防呆掃描上限。
DROP FUNCTION IF EXISTS evaluate_bb_trend(INT, NUMERIC);
CREATE OR REPLACE FUNCTION evaluate_bb_trend(p_scan INT DEFAULT 2000, p_cost NUMERIC DEFAULT 0.006)
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE n INT;
BEGIN
  CREATE TEMP TABLE _px ON COMMIT DROP AS
    SELECT symbol, ts, low*adj_factor AS lo, close*adj_factor AS cl,
           row_number() OVER (PARTITION BY symbol ORDER BY ts) AS rn
    FROM daily_prices WHERE close>0;
  CREATE INDEX ON _px(symbol, rn); CREATE INDEX ON _px(symbol, ts);
  -- ma20（還原）對齊：用 v_price_indicators，★以 ts 對齊（_px/_m 的 rn 起點不同，不可用 rn join）
  CREATE TEMP TABLE _m ON COMMIT DROP AS
    SELECT symbol, ts, ma20
    FROM v_price_indicators WHERE n_window>=20 AND ma20 IS NOT NULL;
  CREATE INDEX ON _m(symbol, ts);

  INSERT INTO prediction_outcomes (analysis_id, exit_price, realized_return, is_win, notes)
  SELECT a.analysis_id, x.exit_price,
    round((x.exit_price/e.cl - 1) - p_cost, 5),
    ((x.exit_price/e.cl - 1) - p_cost) > 0,
    x.reason
  FROM analyses a
  LEFT JOIN prediction_outcomes o ON o.analysis_id=a.analysis_id
  JOIN _px e ON e.symbol=a.symbol AND e.ts=a.as_of
  CROSS JOIN LATERAL (   -- 第一個「跌破20MA 或 −8%停損」的交易日；都沒有 → 無列(未平倉)
    SELECT CASE WHEN f.sl THEN round(e.cl*0.92,4) ELSE f.cl END AS exit_price,
           CASE WHEN f.sl THEN 'stop' ELSE 'ma20_break' END AS reason
    FROM (
      SELECT i.cl, i.rn, (i.lo <= e.cl*0.92) AS sl
      FROM _px i JOIN _m m ON m.symbol=i.symbol AND m.ts=i.ts
      WHERE i.symbol=a.symbol AND i.rn>e.rn AND i.rn<=e.rn+p_scan
        AND (i.lo <= e.cl*0.92 OR i.cl < m.ma20)
      ORDER BY i.rn LIMIT 1
    ) f
  ) x
  WHERE a.skill='strat-bb-trend' AND o.analysis_id IS NULL;
  GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
END $$;
GRANT EXECUTE ON FUNCTION evaluate_bb_trend(INT, NUMERIC) TO stock_app;
