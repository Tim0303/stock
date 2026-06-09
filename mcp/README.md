# mcp — FastMCP server `stock-ai`（owner: mcp-agent / T9）

AI 介面。對外 7001（容器內 8000）。連 DB 角色 **stock_app**（可寫學習+行情，無 DELETE/DDL）。

**待建**：`Dockerfile`、FastMCP app。
**工具**：list_tables / describe_table / run_query(唯讀白名單) / get_latest_price / add_symbol /
get_indicators / get_signals / scan_signals / get_chips / get_strategy / scan_strategy /
run_strategy_5_10_20 / record_analysis / evaluate_predictions / get_accuracy / upsert_skill。

**契約**：`run_query` 必須維持唯讀白名單，擋 DELETE/DDL；不得修改 docker-compose.yml。
