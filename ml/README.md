# ml — sklearn 預測（owner: ml-agent / T7）

一次性容器（`profile=tools`）。連 DB 角色 **stock_app**。

**用法**：`docker compose run --rm ml train` / `ml predict`
**待建**：`Dockerfile`、`features.py`（技術指標+籌碼特徵）、baseline-momentum 與 ml-logreg（LogisticRegression）。

**關鍵契約**：兩者預測都寫進**同一張 analyses 表**（以 `skill` 字串區分 `baseline-momentum` / `ml-logreg`），
走同一評分迴路與 `strat-5-10-20` 同台比較。**只能 INSERT 符合 analyses schema 契約的列，不得改表**；
小資料期屬 baseline 展示，準確率不過度推論；不得修改 docker-compose.yml。
