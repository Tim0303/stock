-- 13_adjust.sql — 還原權值係數（#1, analysis-sql-agent）
-- daily_prices 加「後復權累積係數」adj_factor（預設 1）。
-- 除權息日 adj_factor 跳升，使 close*adj_factor 序列連續，消除市價跳空。
-- 指標/策略/回測一律用「price * adj_factor」（還原價）計算 → 除息不再製造假跌破訊號、報酬含息。
-- 係數由 loader 的 --adjust 模式用 FinMind TaiwanStockDividend 計算後寫入。

ALTER TABLE daily_prices ADD COLUMN IF NOT EXISTS adj_factor NUMERIC NOT NULL DEFAULT 1;
