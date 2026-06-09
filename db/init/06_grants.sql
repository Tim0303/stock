-- 06_grants.sql — 權限（T1, db-schema-agent）
-- 在 03/05 建表後執行。stock_app 可寫但無 DELETE/DDL；stock_readonly 唯讀。
-- 並設 DEFAULT PRIVILEGES，讓之後（07/08/10）建立的表/view/序列自動授權。

-- 既有表（03_core / 05_learning）
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO stock_app;     -- 無 DELETE/TRUNCATE
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO stock_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO stock_readonly;

-- 未來物件（由 stock_admin 在 initdb 後續檔建立者）自動授權
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO stock_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO stock_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO stock_app;          -- 評分/策略 function 可被 MCP 呼叫
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO stock_readonly;         -- 含後續 view
