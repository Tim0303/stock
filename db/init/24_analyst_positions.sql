-- 24_analyst_positions.sql — 分析師持股追蹤（從策略訊號 view 直接推導，物化）
-- 「系統預測當持股」：訊號→隔日開盤進場→各自出場規則→現價/報酬。從 p_since(預設2025-12)起，每日刷新。
-- 與 analyses(學習迴路) 解耦：避免 backtest 標記/去重問題；refresh_analyst_positions() 由 daily_scan 每日重算。
-- 進場＝訊號日隔日開盤(realistic)；出場：5-10-20/spring 走 bracket(壓力/−8%/40日)、bb-trend/bb-breakout 走跌破20MA。
-- 同檔同策略 5 交易日冷卻去重(一波段一筆)。報酬扣 0.6% 成本(平倉)。

CREATE TABLE IF NOT EXISTS analyst_positions (
  skill        text NOT NULL,
  symbol       text NOT NULL,
  name         text,
  signal_date  date NOT NULL,
  entry_date   date,
  entry_price  numeric,
  exit_date    date,
  exit_price   numeric,
  current_price numeric,
  status       text,             -- pending / holding / closed
  ret_pct      numeric,
  score        numeric,
  signal_type  text,
  PRIMARY KEY (skill, symbol, signal_date)
);
GRANT SELECT ON analyst_positions TO stock_readonly, stock_app;

CREATE OR REPLACE FUNCTION refresh_analyst_positions(p_since date DEFAULT '2025-12-01')
RETURNS int LANGUAGE plpgsql AS $$
DECLARE n int;
BEGIN
  CREATE TEMP TABLE _ix ON COMMIT DROP AS
    SELECT symbol, ts, open*adj_factor o, high*adj_factor hi, low*adj_factor lo, close*adj_factor cl,
           row_number() OVER (PARTITION BY symbol ORDER BY ts) rn
    FROM daily_prices WHERE close>0;
  CREATE INDEX ON _ix(symbol, rn); CREATE INDEX ON _ix(symbol, ts);
  CREATE TEMP TABLE _ma ON COMMIT DROP AS
    SELECT symbol, ts, ma20 FROM v_price_indicators WHERE n_window>=20 AND ma20 IS NOT NULL;
  CREATE INDEX ON _ma(symbol, ts);
  CREATE TEMP TABLE _last ON COMMIT DROP AS
    SELECT DISTINCT ON (symbol) symbol, cl FROM _ix ORDER BY symbol, rn DESC;

  -- 訊號集（4 策略）+ 冷卻去重(同檔同策略 rn 間隔>5)
  CREATE TEMP TABLE _sig ON COMMIT DROP AS
  WITH raw AS (
    SELECT 'strat-5-10-20' skill, symbol, ts sig_ts, score, 'bracket' exit_kind FROM v_strategy_5_10_20 WHERE rating='buy' AND ts>=p_since
    UNION ALL SELECT 'strat-bb-trend', symbol, ts, score, 'ma20' FROM v_strategy_5_10_20 WHERE rating='buy' AND ts>=p_since
    UNION ALL SELECT 'strat-spring', symbol, ts, score, 'bracket' FROM v_support_reclaim WHERE signal_type='spring' AND ts>=p_since
    UNION ALL SELECT 'strat-bb-breakout', symbol, ts, score, 'ma20' FROM v_bb_breakout WHERE is_signal AND ts>=p_since
  ),
  g AS (
    SELECT r.*, i.rn, i.rn - lag(i.rn) OVER (PARTITION BY r.skill, r.symbol ORDER BY i.rn) gap
    FROM raw r JOIN _ix i ON i.symbol=r.symbol AND i.ts=r.sig_ts
  )
  SELECT skill, symbol, sig_ts, score, exit_kind, rn FROM g WHERE gap IS NULL OR gap>5;

  TRUNCATE analyst_positions;
  INSERT INTO analyst_positions
  SELECT s.skill, s.symbol, sy.name, s.sig_ts,
    b.ts, round(b.o,2),
    x.exit_date, round(x.exit_price,2),
    round(l.cl,2),
    CASE WHEN b.ts IS NULL THEN 'pending' WHEN x.exit_date IS NOT NULL THEN 'closed' ELSE 'holding' END,
    CASE WHEN b.o>0 AND x.exit_price IS NOT NULL THEN round((x.exit_price/b.o-1-0.006)*100,2)
         WHEN b.o>0 THEN round((l.cl/b.o-1)*100,2) END,
    s.score, 'signal'
  FROM _sig s
  JOIN symbols sy ON sy.symbol=s.symbol
  LEFT JOIN _ix b ON b.symbol=s.symbol AND b.rn=s.rn+1        -- 隔日開盤
  LEFT JOIN _last l ON l.symbol=s.symbol
  LEFT JOIN LATERAL (
    SELECT z.exit_date, z.exit_price FROM (
      SELECT i.ts exit_date, i.cl exit_price, i.rn
      FROM _ix i JOIN _ma m ON m.symbol=i.symbol AND m.ts=i.ts
      WHERE s.exit_kind='ma20' AND b.ts IS NOT NULL AND i.symbol=s.symbol AND i.rn>b.rn AND i.cl<m.ma20
      UNION ALL
      SELECT i.ts, CASE WHEN i.lo<=tt.stop_price THEN tt.stop_price ELSE tt.target_price END, i.rn
      FROM _ix i JOIN v_trade_targets tt ON tt.symbol=s.symbol AND tt.ts=b.ts
      WHERE s.exit_kind='bracket' AND b.ts IS NOT NULL AND i.symbol=s.symbol AND i.rn>b.rn AND i.rn<=b.rn+40
        AND (i.lo<=tt.stop_price OR i.hi>=tt.target_price)
      UNION ALL   -- bracket 40日到期收盤
      SELECT i.ts, i.cl, i.rn
      FROM _ix i WHERE s.exit_kind='bracket' AND b.ts IS NOT NULL AND i.symbol=s.symbol AND i.rn=b.rn+40
    ) z ORDER BY z.rn LIMIT 1
  ) x ON true;

  GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
END $$;
GRANT EXECUTE ON FUNCTION refresh_analyst_positions(date) TO stock_app;

-- 持股追蹤 view 改讀物化表（取代 23 的 analyses 推導版；4 價量策略、2025-12 起完整）。
-- 註：ml-logreg / strat-vcp 為模型/Python 產生，無法廉價回推 2025-12，暫不納入此追蹤（準確率面板仍有）。
DROP VIEW IF EXISTS v_analyst_positions;
CREATE VIEW v_analyst_positions AS
WITH ref AS (SELECT max(ts) AS d FROM daily_prices)
SELECT p.skill, p.symbol, p.name, p.signal_date, p.entry_date, p.entry_price,
       p.exit_date, p.exit_price, p.current_price, p.status, p.ret_pct, p.score, p.signal_type
FROM analyst_positions p, ref
-- 持有中/待進場全顯示；已平倉只留「當月 或 平倉後7日內」(避免歷史平倉洗版)
WHERE p.status <> 'closed'
   OR p.exit_date >= LEAST(date_trunc('month', ref.d)::date, ref.d - 7)
ORDER BY p.skill, (p.status='closed'), p.signal_date DESC;
GRANT SELECT ON v_analyst_positions TO stock_app, stock_readonly;
