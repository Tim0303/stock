-- 12_backtest.sql — 規則化出場回測引擎（#1，analysis-sql-agent）
-- 目的：讓回測反映 5-10-20 策略「真實出場紀律」，而非固定 N 日出場。
-- 出場規則（進場後最早觸發者）：
--   1) 跌破 10MA 收盤（close < ma10）— 策略主防守線，全出
--   2) 固定停損 close <= entry×(1-stop_loss_pct)
-- 並扣除來回交易成本（手續費×2 + 證交稅，台股約 0.6%）。
-- 進場價 = 訊號日收盤（簡化；真實為隔日開盤）。仍是收盤級近似、無移動停利分段減碼。

CREATE TABLE IF NOT EXISTS strategy_backtest_trades (
  symbol      text,
  entry_date  date,
  entry_price numeric,
  exit_date   date,
  exit_price  numeric,
  exit_reason text,
  gross_ret   numeric,   -- 未扣成本
  net_ret     numeric,   -- 扣交易成本後
  hold_days   int
);

CREATE OR REPLACE FUNCTION run_backtest_exits(
  stop_loss_pct numeric DEFAULT 0.05,
  txn_cost      numeric DEFAULT 0.006
)
RETURNS int
LANGUAGE plpgsql
AS $$
DECLARE
  n int;
BEGIN
  TRUNCATE strategy_backtest_trades;

  -- 物化 close/ma10 加速 LATERAL（view 重算窗口太慢）
  CREATE TEMP TABLE _ind ON COMMIT DROP AS
    SELECT symbol, ts, close, ma10 FROM v_price_indicators WHERE n_window >= 20;
  CREATE INDEX ON _ind (symbol, ts);

  INSERT INTO strategy_backtest_trades
  SELECT
    e.symbol, e.entry_date, e.entry_price,
    x.exit_date, x.exit_price, x.exit_reason,
    round((x.exit_price - e.entry_price) / e.entry_price, 5)                   AS gross_ret,
    round((x.exit_price - e.entry_price) / e.entry_price - txn_cost, 5)        AS net_ret,
    (x.exit_date - e.entry_date)                                              AS hold_days
  FROM (
    SELECT symbol, ts AS entry_date, close AS entry_price
    FROM v_strategy_5_10_20
    WHERE rating = 'buy'
  ) e
  CROSS JOIN LATERAL (
    SELECT i.ts AS exit_date, i.close AS exit_price,
      CASE WHEN i.close <= e.entry_price * (1 - stop_loss_pct) THEN 'stop_loss'
           ELSE 'break_ma10' END AS exit_reason
    FROM _ind i
    WHERE i.symbol = e.symbol AND i.ts > e.entry_date
      AND (i.close < i.ma10 OR i.close <= e.entry_price * (1 - stop_loss_pct))
    ORDER BY i.ts
    LIMIT 1                         -- 進場後第一個觸發出場的交易日
  ) x;

  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;

-- 彙總績效（扣成本後 net_ret 為準）
CREATE OR REPLACE VIEW v_strategy_backtest AS
SELECT
  count(*)                                                                     AS n_trades,
  round(avg((net_ret > 0)::int), 3)                                            AS win_rate,
  round(avg(net_ret), 4)                                                       AS avg_net_ret,
  round(sum(net_ret) FILTER (WHERE net_ret > 0)
        / NULLIF(abs(sum(net_ret) FILTER (WHERE net_ret < 0)), 0), 3)          AS profit_factor,
  round(avg(hold_days), 1)                                                     AS avg_hold_days,
  count(*) FILTER (WHERE exit_reason = 'stop_loss')                            AS n_stop_loss,
  count(*) FILTER (WHERE exit_reason = 'break_ma10')                           AS n_break_ma10,
  round(max(net_ret), 3)                                                       AS best,
  round(min(net_ret), 3)                                                       AS worst
FROM strategy_backtest_trades;
