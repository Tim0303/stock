-- 21_eod_intraday_signals.sql — 尾盤即時訊號快照
-- 盤中（預設 13:10）用 TWSE MIS 即時報價當「今日暫定收盤」後，把當下算出的買進候選凍結成快照，
-- 供戰情儀表板「尾盤即時訊號」區塊與 Discord 推播。純預覽，不寫 analyses（正式記錄仍由 15:00 那班負責）。

CREATE TABLE IF NOT EXISTS eod_intraday_signals (
  scan_time    timestamptz NOT NULL,          -- 掃描當下時間（每次掃描一批）
  scan_date    date        NOT NULL,          -- 對應交易日（= 暫定今日）
  skill        text        NOT NULL,          -- strat-5-10-20 / strat-spring / strat-bb-trend / strat-vcp
  symbol       text        NOT NULL,
  name         text,
  score        numeric,                       -- 0–100 訊號強度
  signal_type  text,                          -- 訊號/狀態（buy / A,B,C / spring / 剛突破…）
  close        numeric,                       -- 掃描當下現價（暫定收盤）
  entry_price  numeric,                       -- 進場參考價
  target_price numeric,                       -- 壓力目標（趨勢續抱/VCP 可能為 NULL）
  stop_price   numeric,                       -- 停損
  meta         jsonb       NOT NULL DEFAULT '{}',
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scan_time, skill, symbol)
);

CREATE INDEX IF NOT EXISTS idx_eod_signals_latest
  ON eod_intraday_signals (scan_date DESC, skill, score DESC NULLS LAST);

GRANT SELECT ON eod_intraday_signals TO stock_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE ON eod_intraday_signals TO stock_app;

-- 把「掃描當下四位價量分析師的買進候選」凍結成一筆快照（以 now() 為 scan_time）。
-- 讀 v_strategy_latest / v_support_reclaim_latest / v_bb_trend_latest / vcp_watchlist，皆以暫定今日(max ts)為準。
CREATE OR REPLACE FUNCTION snapshot_eod_signals() RETURNS integer AS $$
DECLARE
  v_t timestamptz := now();
  v_d date        := (SELECT max(ts) FROM daily_prices);
  n   integer;
BEGIN
  INSERT INTO eod_intraday_signals
    (scan_time, scan_date, skill, symbol, name, score, signal_type, close, entry_price, target_price, stop_price, meta)
  -- 5-10-20 短線順勢（rating=buy）
  SELECT v_t, v_d, 'strat-5-10-20', l.symbol, sy.name, l.score, l.signal_type, l.close, l.close,
         l.target_price, l.stop_price,
         jsonb_build_object('rating', l.rating, 'bias_ma20', l.bias_ma20, 'bias_ma10', l.bias_ma10)
  FROM v_strategy_latest l JOIN symbols sy USING (symbol)
  WHERE l.rating = 'buy' AND l.ts = v_d
  UNION ALL
  -- 破支撐拉回 spring
  SELECT v_t, v_d, 'strat-spring', s.symbol, sy.name, s.score, s.signal_type, s.close, s.close,
         s.target_price, s.stop_price,
         jsonb_build_object('above_sup_pct', s.above_sup_pct, 'range20_pct', s.range20_pct, 'vol_ratio', s.vol_ratio)
  FROM v_support_reclaim_latest s JOIN symbols sy USING (symbol)
  WHERE s.signal_type = 'spring' AND s.ts = v_d
  UNION ALL
  -- 布林通道趨勢續抱（沿用 5-10-20 進場，無壓力目標上限）
  SELECT v_t, v_d, 'strat-bb-trend', b.symbol, sy.name, b.score, b.signal_type, b.entry_price, b.entry_price,
         NULL, b.stop_price,
         jsonb_build_object('exit_rule', b.exit_rule)
  FROM v_bb_trend_latest b JOIN symbols sy USING (symbol)
  WHERE b.ts = v_d
  UNION ALL
  -- 布林開口放量突破（出場單一標準=跌破20MA，無壓力目標；以暫定今日盤算訊號）
  SELECT v_t, v_d, 'strat-bb-breakout', bk.symbol, sy.name, bk.score, 'breakout', bk.close, bk.close,
         NULL, bk.ma20,
         jsonb_build_object('vol_ratio', bk.vol_ratio, 'bw_ratio', bk.bw_ratio, 'exit_rule', '跌破20MA')
  FROM v_bb_breakout bk JOIN symbols sy USING (symbol)
  WHERE bk.is_signal AND bk.ts = v_d
  UNION ALL
  -- VCP 剛突破（vcp_watchlist 最新一批；尾盤前先跑 vcp watchlist 以暫定盤刷新）
  SELECT v_t, v_d, 'strat-vcp', w.symbol, w.name, w.score, w.status, w.close, w.close,
         NULL, NULL,
         jsonb_build_object('pivot', w.pivot, 'distance_pct', w.distance_pct, 'contraction_count', w.contraction_count)
  FROM vcp_watchlist w
  WHERE w.scan_date = (SELECT max(scan_date) FROM vcp_watchlist)
    AND w.status LIKE '剛突破%';

  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$ LANGUAGE plpgsql;
