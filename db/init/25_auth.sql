-- 25_auth.sql — 訂閱制：使用者帳號 + Email 驗證/密碼重設 token + 訂閱狀態（auth-agent）
-- 自建登入/註冊（argon2 雜湊在 API 端做；本檔只存 password_hash 與 token 的 SHA-256）。
-- ★最小權限：因 06_grants.sql 設了 DEFAULT PRIVILEGES 會自動把新表授權給 stock_app/stock_readonly，
--   本檔建表後「明確 REVOKE」掉，使這 4 張含 PII 的表「只有 stock_auth」能存取（API 用專屬連線）。
-- 套用（既有 volume）：docker cp 25_auth.sql → docker exec -e STOCK_AUTH_PASSWORD=... psql -U stock_admin -f
-- 冪等：IF NOT EXISTS / CREATE OR REPLACE，可重複套用、新環境亦會 initdb 自動跑。

-- ── 1) 專屬 login role：只寫 auth 表，碰不到既有股票資料表 ───────────────────
\getenv auth_pw STOCK_AUTH_PASSWORD
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'stock_auth') THEN
    CREATE ROLE stock_auth LOGIN;
  END IF;
END $$;
ALTER ROLE stock_auth PASSWORD :'auth_pw';
GRANT CONNECT ON DATABASE stockdb TO stock_auth;
GRANT USAGE ON SCHEMA public TO stock_auth;

-- ── 2) 使用者 ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS app_users (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  email          text        NOT NULL,                 -- 一律存小寫；API 端 normalize
  email_verified boolean     NOT NULL DEFAULT false,
  password_hash  text        NOT NULL,                 -- argon2 編碼字串
  disabled       boolean     NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  last_login_at  timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_app_users_email ON app_users (lower(email));

-- ── 3) Email 驗證 / 密碼重設 token（只存 SHA-256(raw)，原始 token 只在信中）──────
CREATE TABLE IF NOT EXISTS email_verification_tokens (
  token_hash text        PRIMARY KEY,                  -- sha256 hex of raw token
  user_id    uuid        NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  used_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_evt_user ON email_verification_tokens (user_id);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
  token_hash text        PRIMARY KEY,
  user_id    uuid        NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  used_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_prt_user ON password_reset_tokens (user_id);

-- ── 4) 訂閱狀態機（付款欄位預留 nullable，Phase 2 webhook 會填）──────────────────
CREATE TABLE IF NOT EXISTS subscriptions (
  id                      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                 uuid        NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
  status                  text        NOT NULL CHECK (status IN ('trialing','active','past_due','canceled','expired')),
  plan                    text        NOT NULL DEFAULT 'trial',
  trial_end               timestamptz,
  current_period_end      timestamptz,
  provider                text,       -- 'ecpay' / 'newebpay'（Phase 2）
  provider_customer_id    text,
  provider_subscription_id text,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz NOT NULL DEFAULT now()
);
-- 一人至多一張「有效」訂閱（試用/付費/逾期）
CREATE UNIQUE INDEX IF NOT EXISTS idx_sub_user_live
  ON subscriptions (user_id) WHERE status IN ('trialing','active','past_due');
CREATE INDEX IF NOT EXISTS idx_sub_user ON subscriptions (user_id);

-- ── 5) 最小權限收斂：撤掉 DEFAULT PRIVILEGES 自動給的授權，只留 stock_auth ─────────
REVOKE ALL ON app_users, email_verification_tokens, password_reset_tokens, subscriptions
  FROM stock_app, stock_readonly;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON app_users, email_verification_tokens, password_reset_tokens, subscriptions
  TO stock_auth;
