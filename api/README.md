# api — FastAPI 唯讀 REST（owner: api-agent / T10）

人介面後端。對外 7003（容器內 8000）。連 DB 角色 **stock_readonly**（唯讀）。

**待建**：`Dockerfile`、FastAPI app、**先產出 OpenAPI/路由契約**供 web-agent 對齊。
**路由**：`/api/candidates` `/api/accuracy` `/api/indicators` `/api/skills` `/api/chips` `/api/strategy`。

**契約**：唯讀（角色層擋寫入）；路由前綴 `/api`（nginx 反代同源）；不得修改 docker-compose.yml。
