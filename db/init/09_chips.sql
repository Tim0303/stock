-- 09_chips.sql — 台股籌碼表（chiploader-agent）
-- 建表 IF NOT EXISTS；PK (symbol, ts)；由 stock_admin 建立，
-- DEFAULT PRIVILEGES（06_grants.sql）自動授權 stock_app/stock_readonly。

-- ── 三大法人買賣超（淨額，股） ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chip_institutional (
    symbol       text        NOT NULL,   -- e.g. '2330.TW'
    ts           date        NOT NULL,   -- 交易日
    foreign_net  numeric,                -- 外資淨買超（Foreign_Investor buy-sell）
    trust_net    numeric,                -- 投信淨買超（Investment_Trust buy-sell）
    dealer_net   numeric,                -- 自營商淨買超（Dealer_self+Dealer_Hedging+Foreign_Dealer_Self）
    total_net    numeric,                -- 三大法人合計淨買超
    PRIMARY KEY (symbol, ts)
);

-- ── 融資券餘額與增減 ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS chip_margin (
    symbol          text    NOT NULL,   -- e.g. '2330.TW'
    ts              date    NOT NULL,   -- 交易日
    margin_balance  bigint,             -- 融資餘額（MarginPurchaseTodayBalance）
    margin_change   bigint,             -- 融資增減 = today - yesterday
    short_balance   bigint,             -- 融券餘額（ShortSaleTodayBalance）
    short_change    bigint,             -- 融券增減 = today - yesterday
    PRIMARY KEY (symbol, ts)
);
