# web — React 戰情儀表板（owner: web-agent / T11）

人看資料的主入口。對外 7004（容器內 80，nginx）。React + Vite + Tailwind + ECharts。

**待建**：`Dockerfile`（多階段 build → nginx）、前端 app。`nginx.conf` 骨架已由 infra 提供（/api 同源反代）。
**看板**：候選榜首頁 / 三方準確率 / 技能績效排行 / 標的 K 線疊均線 / 近期分析 / 待評。

**契約**：照 api-agent 的 OpenAPI 契約開發；資料一律走 `/api`（同源）；不得修改 docker-compose.yml。
