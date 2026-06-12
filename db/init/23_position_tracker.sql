-- 23_position_tracker.sql — 分析師持股追蹤（live 訊號當持股：進場→出場/現價→報酬）
-- 把每位分析師寫進 analyses 的 live 訊號當成「模擬持股」：
--   進場 = analyses(as_of, entry_price)；出場 = prediction_outcomes(exit_date, exit_price, realized_return)；
--   未平倉 = 顯示現價與未實現報酬。供儀表板「分析師持股」面板（/api/analyst-positions）。

-- 出場日期欄（評分函式 19/20/22 已更新為記錄 exit_date；此處補欄 + 回補既有記錄）
ALTER TABLE prediction_outcomes ADD COLUMN IF NOT EXISTS exit_date DATE;

-- 回補既有 live 已平倉記錄的 exit_date（通用法：出場價落在某交易日[還原低,高]區間內的「最早」交易日）
WITH px AS (
  SELECT symbol, ts, low*adj_factor AS lo, high*adj_factor AS hi,
         row_number() OVER (PARTITION BY symbol ORDER BY ts) AS rn
  FROM daily_prices WHERE close>0
)
UPDATE prediction_outcomes o SET exit_date = sub.xd
FROM (
  SELECT a.analysis_id,
    (SELECT i.ts FROM px i JOIN px e ON e.symbol=a.symbol AND e.ts=a.as_of
     WHERE i.symbol=a.symbol AND i.rn>e.rn
       AND o2.exit_price BETWEEN i.lo*0.999 AND i.hi*1.001
     ORDER BY i.rn LIMIT 1) AS xd
  FROM analyses a
  JOIN prediction_outcomes o2 ON o2.analysis_id=a.analysis_id
  WHERE (a.meta->>'backtest') IS DISTINCT FROM 'true' AND o2.exit_date IS NULL
) sub
WHERE o.analysis_id=sub.analysis_id AND sub.xd IS NOT NULL;

-- 持股追蹤 view（現役 6 分析師、僅 live 非回測）
-- ★ 進場＝訊號日(as_of) 的「隔日開盤」(realistic，與報告真實模擬一致；不可能用訊號日收盤買到)。
--   未到隔日(今日剛發訊號)→ status='pending'(待進場)。報酬一律以隔日開盤為基準(扣0.6%成本於平倉)。
--   註：此處報酬是「跟單真實執行」視角，與「準確率面板」(訊號日收盤評分、學習迴路用)基準不同，屬正常。
CREATE OR REPLACE VIEW v_analyst_positions AS
WITH px AS (
  SELECT symbol, ts, open*adj_factor AS o, close*adj_factor AS c,
         row_number() OVER (PARTITION BY symbol ORDER BY ts) AS rn
  FROM daily_prices WHERE close>0
),
cur AS (SELECT DISTINCT ON (symbol) symbol, round(c::numeric,2) AS cur_px FROM px ORDER BY symbol, ts DESC),
ent AS (   -- 隔日開盤進場（訊號日 as_of 的下一個交易日 open）
  SELECT a.analysis_id, n.ts AS buy_date, round(n.o::numeric,2) AS buy_open
  FROM analyses a
  JOIN px e ON e.symbol=a.symbol AND e.ts=a.as_of
  JOIN px n ON n.symbol=a.symbol AND n.rn=e.rn+1
)
SELECT a.skill, a.symbol, sy.name,
  ent.buy_date AS entry_date, ent.buy_open AS entry_price,
  o.exit_date, round(o.exit_price,2) AS exit_price,
  cur.cur_px AS current_price,
  CASE WHEN o.analysis_id IS NOT NULL THEN 'closed'
       WHEN ent.buy_open IS NULL     THEN 'pending'
       ELSE 'holding' END AS status,
  CASE WHEN o.analysis_id IS NOT NULL AND ent.buy_open>0
         THEN round((o.exit_price/ent.buy_open - 1 - 0.006)*100, 2)   -- 平倉：出場/隔日開盤，扣成本
       WHEN ent.buy_open>0
         THEN round((cur.cur_px/ent.buy_open - 1)*100, 2)             -- 持有中：現價/隔日開盤(未實現)
  END AS ret_pct,
  o.is_win, a.score, a.signal_type, a.as_of AS signal_date
FROM analyses a
JOIN symbols sy USING (symbol)
LEFT JOIN ent ON ent.analysis_id = a.analysis_id
LEFT JOIN prediction_outcomes o ON o.analysis_id = a.analysis_id
LEFT JOIN cur ON cur.symbol = a.symbol
WHERE (a.meta->>'backtest') IS DISTINCT FROM 'true'
  AND a.skill IN ('strat-vcp','strat-5-10-20','strat-spring','strat-bb-trend','strat-bb-breakout','ml-logreg')
ORDER BY a.skill, (o.analysis_id IS NOT NULL), a.as_of DESC;
GRANT SELECT ON v_analyst_positions TO stock_app, stock_readonly;
