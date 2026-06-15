-- 11_scan_evolve.sql — 每日掃描 + 技能演化（scheduler-agent）★學習迴路關鍵環
-- 1) daily_candidates：每日掃描快照（近期 buy/watch，已濾殭屍股）
-- 2) scan_strategy_candidates()：寫入當日候選，依 score 排序給 rank
-- 3) refresh_skill_performance()：回填 champion 績效欄位（n_predictions/win_rate/...）
-- 4) evolve_strategy()：演化器框架，含過度擬合保守鎖（n<30 只記錄不換冠軍）
-- 5) TimescaleDB 排程：wrapper procedure + add_job（掃描每日、演化每週）
-- 鐵律：所有掃描/候選一律過濾 ts >= max(ts)-5d（濾下市殭屍股）；保守鎖務必正確。

-- ── 1) 每日候選快照表 ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS daily_candidates (
  scan_date           date        NOT NULL,
  market              text,
  symbol              text        NOT NULL,
  skill_id            bigint,
  score               numeric,
  rating              text,
  signal_type         text,
  rank                int,
  snapshot_params_hash text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (scan_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_daily_candidates_scan_rank
  ON daily_candidates (scan_date, rank);

-- 綜合排行榜欄位：skill=該檔最高分的分析師、n_skills=共幾位分析師看好
ALTER TABLE daily_candidates ADD COLUMN IF NOT EXISTS skill    text;
ALTER TABLE daily_candidates ADD COLUMN IF NOT EXISTS n_skills int;

-- ── 2) 掃描：6 位分析師「綜合排行榜」寫入 daily_candidates ─────────────────
-- UNION 6 位分析師的當前買進級推薦（5-10-20/spring/bb-trend/bb-breakout 走各自 latest view、
--   vcp 走 watchlist 剛突破、ml-logreg 走 analyses live predicted=up），各檔過濾近5日(濾殭屍)。
-- 每檔去重取「最高分的分析師」並計 n_skills(幾位看好)；排名依 n_skills desc → score desc（共識優先）。
-- scan_date 一律用最新交易日，PK(scan_date,symbol) 確保一檔一列。
CREATE OR REPLACE FUNCTION scan_strategy_candidates()
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
  n INT;
  v_d date;
BEGIN
  v_d := (SELECT max(ts) FROM daily_prices);
  DELETE FROM daily_candidates WHERE scan_date = v_d;   -- 當日重算，去除已不再入選者

  WITH picks AS (
    SELECT 'strat-5-10-20'::text skill, 1::bigint skill_id, l.symbol, l.score::numeric AS score, l.signal_type::text AS signal_type
    FROM v_strategy_latest l WHERE l.rating='buy' AND l.ts >= v_d - 5
    UNION ALL
    SELECT 'strat-spring', 10, s.symbol, s.score, s.signal_type
    FROM v_support_reclaim_latest s WHERE s.signal_type='spring' AND s.ts >= v_d - 5
    UNION ALL
    SELECT 'strat-bb-trend', 15, b.symbol, b.score, b.signal_type
    FROM v_bb_trend_latest b WHERE b.ts >= v_d - 5
    UNION ALL
    SELECT 'strat-bb-breakout', 20, bk.symbol, bk.score, bk.signal_type
    FROM v_bb_breakout_latest bk WHERE bk.ts >= v_d - 5
    UNION ALL
    SELECT 'strat-vcp', 8, w.symbol, w.score, w.status
    FROM vcp_watchlist w
    WHERE w.scan_date = (SELECT max(scan_date) FROM vcp_watchlist) AND w.status LIKE '剛突破%'
    UNION ALL
    SELECT 'ml-logreg', NULL::bigint, a.symbol, a.score, a.signal_type
    FROM analyses a
    WHERE a.skill='ml-logreg' AND (a.meta->>'backtest') IS DISTINCT FROM 'true' AND a.predicted='up'
      AND a.as_of = (SELECT max(as_of) FROM analyses
                     WHERE skill='ml-logreg' AND (meta->>'backtest') IS DISTINCT FROM 'true')
  ),
  best AS (   -- 每檔取最高分的分析師 + 計 n_skills(幾位看好)
    SELECT DISTINCT ON (symbol)
      symbol, skill, skill_id, score, signal_type,
      count(*) OVER (PARTITION BY symbol) AS n_skills
    FROM picks
    ORDER BY symbol, score DESC NULLS LAST
  ),
  final AS (
    SELECT b.*, sy.market,
      row_number() OVER (ORDER BY b.n_skills DESC, b.score DESC NULLS LAST, b.symbol) AS rank
    FROM best b LEFT JOIN symbols sy ON sy.symbol = b.symbol
  )
  INSERT INTO daily_candidates
    (scan_date, market, symbol, skill, skill_id, score, rating, signal_type, rank, n_skills)
  SELECT v_d, f.market, f.symbol, f.skill, f.skill_id, f.score, 'buy', f.signal_type, f.rank, f.n_skills
  FROM final f;

  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END;
$$;

-- ── 3) 回填 champion 績效欄位 ────────────────────────────────────────
-- 從 analyses join prediction_outcomes 聚合各 family 的實盤表現，
-- 回填到對應 champion row（n_predictions / win_rate / avg_return / profit_factor / last_evaluated_at）。
CREATE OR REPLACE FUNCTION refresh_skill_performance()
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
  WITH perf AS (
    SELECT
      a.skill,
      count(*)                                            AS n_pred,
      avg(CASE WHEN o.is_win THEN 1 ELSE 0 END)::numeric  AS win_rate,
      avg(o.realized_return)::numeric                     AS avg_return,
      ( COALESCE(sum(o.realized_return) FILTER (WHERE o.realized_return > 0), 0)
        / NULLIF(abs(sum(o.realized_return) FILTER (WHERE o.realized_return < 0)), 0)
      )::numeric                                          AS profit_factor
    FROM analyses a
    JOIN prediction_outcomes o USING (analysis_id)
    GROUP BY a.skill
  )
  UPDATE skills sk
  SET
    n_predictions     = perf.n_pred,
    win_rate          = round(perf.win_rate, 4),
    avg_return        = round(perf.avg_return, 5),
    profit_factor     = round(perf.profit_factor, 3),
    last_evaluated_at = now()
  FROM perf
  WHERE sk.family = perf.skill
    AND sk.status = 'champion';
END;
$$;

-- ── 4) 演化器（含過度擬合保守鎖）────────────────────────────────────
-- 流程：先刷新績效 → 取 champion n_predictions →
--   n<30：回傳「樣本不足，冠軍維持不變」，絕不變更 skills（保守鎖）。
--   n>=30：複製 champion params，對 enter_threshold 做 {75,80,85} 一維變化，
--          算 param_hash=md5(params::text)，INSERT 為 status='candidate'、parent=champion。
--          walk-forward 實評留待後續，先建框架。
CREATE OR REPLACE FUNCTION evolve_strategy()
RETURNS text
LANGUAGE plpgsql
AS $$
DECLARE
  v_champ_id     bigint;
  v_champ_params jsonb;
  v_n            int;
  v_thr          int;
  v_new_params   jsonb;
  v_new_hash     text;
  v_inserted     int := 0;
  v_rc           int;
BEGIN
  -- 先回填最新實盤績效
  PERFORM refresh_skill_performance();

  SELECT skill_id, params, COALESCE(n_predictions, 0)
    INTO v_champ_id, v_champ_params, v_n
  FROM skills
  WHERE family = 'strat-5-10-20' AND status = 'champion'
  ORDER BY version DESC LIMIT 1;

  IF v_champ_id IS NULL THEN
    RETURN '找不到 strat-5-10-20 冠軍，演化中止';
  END IF;

  -- ★ 過度擬合保守鎖：實盤已評分樣本不足 30，只記錄、絕不換冠軍/不調參/不建候選
  IF v_n < 30 THEN
    RETURN format('樣本不足(n=%s)，冠軍維持不變', v_n);
  END IF;

  -- 樣本足夠：對 enter_threshold 做一維掃描，建 candidate（框架；實評後續）
  FOREACH v_thr IN ARRAY ARRAY[75, 80, 85]
  LOOP
    v_new_params := jsonb_set(v_champ_params, '{enter_threshold}', to_jsonb(v_thr));
    v_new_hash   := md5(v_new_params::text);

    INSERT INTO skills
      (family, version, status, market_scope, params, param_hash, parent_skill_id, created_by, notes)
    SELECT
      'strat-5-10-20',
      (SELECT COALESCE(max(version), 0) + 1 FROM skills WHERE family = 'strat-5-10-20'),
      'candidate', 'ALL', v_new_params, v_new_hash, v_champ_id, 'evolver',
      format('enter_threshold 一維變化 -> %s（walk-forward 實評待後續）', v_thr)
    ON CONFLICT (family, param_hash) DO NOTHING;

    GET DIAGNOSTICS v_rc = ROW_COUNT;
    v_inserted := v_inserted + v_rc;
  END LOOP;

  RETURN format('樣本足夠(n=%s)，產生 %s 個 enter_threshold 候選（status=candidate，待 walk-forward 實評）',
                v_n, v_inserted);
END;
$$;

-- ── 5) TimescaleDB 排程：wrapper procedure + add_job ─────────────────
-- 掃描每日一次；演化每週一次。procedure 簽名須 (job_id INT, config JSONB)。
CREATE OR REPLACE PROCEDURE job_scan_candidates(job_id INT, config JSONB)
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM scan_strategy_candidates();
END;
$$;

CREATE OR REPLACE PROCEDURE job_evolve_strategy(job_id INT, config JSONB)
LANGUAGE plpgsql
AS $$
BEGIN
  PERFORM evolve_strategy();
END;
$$;

-- 冪等掛 job：先刪同名舊 job，再新增（避免重複套用本檔時堆疊多份）
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT job_id FROM timescaledb_information.jobs
    WHERE proc_name IN ('job_scan_candidates', 'job_evolve_strategy')
  LOOP
    PERFORM delete_job(r.job_id);
  END LOOP;
END;
$$;

SELECT add_job('job_scan_candidates',  schedule_interval => INTERVAL '1 day');
SELECT add_job('job_evolve_strategy',  schedule_interval => INTERVAL '7 days');
