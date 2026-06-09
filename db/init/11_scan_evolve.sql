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

-- ── 2) 掃描：寫入當日近期 buy/watch 候選 ─────────────────────────────
-- 來源 v_strategy_latest（每檔最新一日）。過濾：ts >= max(ts)-5d（濾殭屍股）
-- 且 rating in('buy','watch')。依 score desc 排 rank。
-- scan_date 用該檔自身的 ts；market 由 symbols join；snapshot_params_hash 取 champion param_hash。
CREATE OR REPLACE FUNCTION scan_strategy_candidates()
RETURNS INT
LANGUAGE plpgsql
AS $$
DECLARE
  n INT;
  v_champ_hash text;
BEGIN
  SELECT param_hash INTO v_champ_hash
  FROM skills
  WHERE family = 'strat-5-10-20' AND status = 'champion'
  ORDER BY version DESC LIMIT 1;

  WITH recent AS (
    SELECT
      l.symbol, l.ts, l.skill_id, l.score, l.rating, l.signal_type,
      s.market,
      row_number() OVER (ORDER BY l.score DESC, l.symbol) AS rnk
    FROM v_strategy_latest l
    LEFT JOIN symbols s ON s.symbol = l.symbol
    WHERE l.rating IN ('buy', 'watch')
      -- 濾下市/停止交易殭屍股：只收最新資料近 5 日內者
      AND l.ts >= (SELECT max(ts) FROM daily_prices) - INTERVAL '5 days'
  )
  INSERT INTO daily_candidates
    (scan_date, market, symbol, skill_id, score, rating, signal_type, rank, snapshot_params_hash)
  SELECT
    r.ts, r.market, r.symbol, r.skill_id, r.score, r.rating, r.signal_type, r.rnk, v_champ_hash
  FROM recent r
  ON CONFLICT (scan_date, symbol) DO UPDATE SET
    market               = EXCLUDED.market,
    skill_id             = EXCLUDED.skill_id,
    score                = EXCLUDED.score,
    rating               = EXCLUDED.rating,
    signal_type          = EXCLUDED.signal_type,
    rank                 = EXCLUDED.rank,
    snapshot_params_hash = EXCLUDED.snapshot_params_hash,
    created_at           = now();

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
