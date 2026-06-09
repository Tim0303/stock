-- 15_vcp_watchlist.sql — VCP 突破監控清單（dashboard-agent / 第五分析師看板）
-- vcp/main.py 的 watchlist 子命令每次掃描後寫入本表；
-- API /api/vcp-watchlist 讀「最新 scan_date」清單供 7004 戰情儀表板呈現。
-- 鐵律：純展示用快照，非預測（analyses 才是預測）。不改 vcp_core 偵測邏輯。
-- GRANT 由 06_grants.sql 的 DEFAULT PRIVILEGES 自動處理（stock_app 可寫、stock_readonly 唯讀）。

CREATE TABLE IF NOT EXISTS vcp_watchlist (
  scan_date          date     NOT NULL,
  symbol             text     NOT NULL,
  name               text,
  close              numeric,
  pivot              numeric,
  distance_pct       numeric,         -- close 相對 pivot 的距離（%）
  contraction_count  int,             -- 收縮次數
  last_drawdown_pct  numeric,         -- 末次收縮回檔幅度（%）
  score              numeric,         -- 0-100 VCP 評分
  status             text,            -- '剛突破' / '待突破(量縮)' / '待突破'
  vol_dry            boolean,         -- 量縮乾涸
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scan_date, symbol)
);

COMMENT ON TABLE vcp_watchlist IS 'VCP 突破監控清單快照（每日 watchlist 掃描寫入，供戰情儀表板）';
