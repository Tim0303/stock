-- 02_roles.sql — 應用角色（T1, db-schema-agent）
-- 密碼從容器環境變數帶入（psql 16 \getenv，避免把密碼寫死在檔案）。
-- 角色職責：
--   stock_app      MCP/loader/ml 用——可 SELECT/INSERT/UPDATE 行情+學習表，無 DELETE/DDL
--   stock_readonly API 用——唯讀
\getenv app_pw STOCK_APP_PASSWORD
\getenv ro_pw STOCK_READONLY_PASSWORD

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'stock_app') THEN
    CREATE ROLE stock_app LOGIN;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'stock_readonly') THEN
    CREATE ROLE stock_readonly LOGIN;
  END IF;
END $$;

-- 頂層 SQL：psql 變數替換成 quoted literal
ALTER ROLE stock_app PASSWORD :'app_pw';
ALTER ROLE stock_readonly PASSWORD :'ro_pw';

GRANT CONNECT ON DATABASE stockdb TO stock_app, stock_readonly;
GRANT USAGE ON SCHEMA public TO stock_app, stock_readonly;
-- 不授 CREATE on schema → 兩角色皆無 DDL
