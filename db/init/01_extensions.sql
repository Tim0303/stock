-- 01_extensions.sql — 啟用擴充（骨架，infra-agent / T0）
-- db/init/*.sql 在 TimescaleDB「首次初始化」時依檔名序自動執行。
-- 編號約定（由 infra-agent 統一發，一檔一 owner、不重疊）：
--   01_extensions  擴充（本檔）
--   02_roles       應用角色 stock_app / stock_readonly        (T1)
--   03_core        symbols / daily_prices(hypertable)         (T1)
--   05_learning    skills / analyses / prediction_outcomes    (T1)
--   07_jobs        evaluate_due_predictions() + 排程 + 種子冠軍 (T2)
--   08_indicators  ema() + v_price_indicators                 (T4)
--   09_chips       chip_institutional / chip_margin           (T6)
--   10_strategy_5_10_20  v_strategy_5_10_20 + record_strategy_signals (T5)

CREATE EXTENSION IF NOT EXISTS timescaledb;
