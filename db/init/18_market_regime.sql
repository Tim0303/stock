-- 18_market_regime.sql — 大盤體質代理（universe 寬度：% 個股站上 20MA）
-- 用途：大盤過濾——空頭(寬度崩)時不開倉，補回測 2022 破口。無需外部指數，自 universe 計算。
-- market_ok = 當日逾半數個股站上 20MA（大盤健康）。breadth_ma10 = 寬度10日均(平滑)。

CREATE OR REPLACE VIEW v_market_regime AS
WITH d AS (
  SELECT ts, avg((close > ma20)::int)::numeric AS breadth
  FROM v_price_indicators
  WHERE n_window >= 20 AND ma20 IS NOT NULL AND close > 0
  GROUP BY ts
)
SELECT ts,
  round(breadth*100, 1)                                                            AS breadth_pct,
  round(avg(breadth*100) OVER (ORDER BY ts ROWS BETWEEN 9 PRECEDING AND CURRENT ROW), 1) AS breadth_ma10,
  (breadth >= 0.50)                                                                AS market_ok
FROM d;

GRANT SELECT ON v_market_regime TO stock_app, stock_readonly;

-- 今日大盤是否健康（最新交易日 market_ok）；無資料時預設 true（不誤擋）。
-- 記錄函式 / 推薦查詢用此當開倉閘門：空頭(寬度<50%)時不開倉。
CREATE OR REPLACE FUNCTION market_ok_now() RETURNS boolean
LANGUAGE sql STABLE AS $$
  SELECT COALESCE((SELECT market_ok FROM v_market_regime ORDER BY ts DESC LIMIT 1), true);
$$;
GRANT EXECUTE ON FUNCTION market_ok_now() TO stock_app, stock_readonly;
