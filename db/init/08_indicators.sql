-- 08_indicators.sql — 技術指標（T4, analysis-sql-agent）
-- DB 端窗口函數計算 5/10/20MA、量能、前5日高、乖離、均線斜率。
-- v_strategy_5_10_20（T5）建在此 view 之上。

CREATE OR REPLACE VIEW v_price_indicators AS
WITH base AS (
  SELECT
    symbol, ts, open, high, low, close, volume,
    avg(close)  OVER w5   AS ma5,
    avg(close)  OVER w10  AS ma10,
    avg(close)  OVER w20  AS ma20,
    avg(volume) OVER w5   AS vol_ma5,
    max(high)   OVER w5p  AS prev_high_5,   -- 前 5 日（不含當日）最高 → 突破判斷
    count(*)    OVER w20  AS n_window        -- 累積筆數，<20 時 ma20 尚不完整
  FROM daily_prices
  WINDOW
    w5  AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 4  PRECEDING AND CURRENT ROW),
    w10 AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 9  PRECEDING AND CURRENT ROW),
    w20 AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
    w5p AS (PARTITION BY symbol ORDER BY ts ROWS BETWEEN 5  PRECEDING AND 1 PRECEDING)
)
SELECT
  base.*,
  lag(close) OVER ph AS close_prev,
  lag(ma5)   OVER ph AS ma5_prev,
  lag(ma20)  OVER ph AS ma20_prev,
  CASE WHEN ma10 > 0 THEN (close - ma10) / ma10 END AS bias_ma10,
  CASE WHEN ma20 > 0 THEN (close - ma20) / ma20 END AS bias_ma20
FROM base
WINDOW ph AS (PARTITION BY symbol ORDER BY ts);
