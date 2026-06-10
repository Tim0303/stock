"""
main.py — ML 分析師進入點。

子命令：
  train    : 訓練 ml-logreg（LogisticRegression），存模型 models/logreg.pkl，
             並印訓練樣本數與 train accuracy。
  predict  : 對最新交易日的近期標的，寫入 ml-logreg 預測到 analyses（載入模型，輸出上漲機率）。
             （baseline-momentum 對照已移除：純對照、無實用價值。）

契約：
  - 只 INSERT 符合 analyses schema 的列，不改表、不刪資料。
  - horizon_days=5；due_date = as_of + 7 日曆日（5*1.4 取整）。
  - entry_price = 當日 close。
  - 只對近期標的（最新 ts >= max(ts)-5 天）做預測。

誠實說明：資料量小（55 檔、單一切點），ml-logreg 屬 baseline 展示，
非追 alpha；train accuracy 僅供 sanity check，不過度推論。
"""

from __future__ import annotations

import os
import pickle
import sys
from datetime import timedelta

import numpy as np
import pandas as pd
import psycopg2

import features as F

MODEL_PATH = os.path.join(os.path.dirname(__file__), "models", "logreg.pkl")
HORIZON_DAYS = F.HORIZON_DAYS          # 5
DUE_OFFSET_DAYS = round(HORIZON_DAYS * 1.4)  # 7 日曆日，與 strat 對齊


def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[error] DATABASE_URL 未設定", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(url)


# --------------------------------------------------------------------------- #
# train
# --------------------------------------------------------------------------- #
def _fit_model(conn, tag="train"):
    """訓練 LogisticRegression 並回傳 bundle dict。共用於 train 與 predict 後備。"""
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline

    X, y, _ = F.training_xy(conn, horizon=HORIZON_DAYS)
    n = len(y)
    if n < 50:
        print(f"[error] 訓練樣本太少 ({n})，中止。", file=sys.stderr)
        sys.exit(1)

    pos = int(y.sum())
    print(f"[{tag}] 訓練樣本數: {n}  (漲={pos}, 跌={n - pos}, "
          f"正樣本比={pos / n:.3f})")
    print(f"[{tag}] 特徵 ({len(F.FEATURE_COLS)}): {', '.join(F.FEATURE_COLS)}")

    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=1000, C=1.0)),
    ])
    model.fit(X, y)

    acc = model.score(X, y)
    print(f"[{tag}] train accuracy: {acc:.4f} "
          f"(in-sample，僅 sanity check；小資料下屬 baseline 展示)")

    return {"model": model, "feature_cols": F.FEATURE_COLS,
            "horizon": HORIZON_DAYS}


def cmd_train():
    conn = get_conn()
    try:
        bundle = _fit_model(conn, tag="train")
    finally:
        conn.close()

    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(bundle, f)
    print(f"[train] 模型已存: {MODEL_PATH}")


# --------------------------------------------------------------------------- #
# predict 共用 INSERT
# --------------------------------------------------------------------------- #
_INSERT_SQL = """
    INSERT INTO analyses
        (symbol, skill, skill_id, as_of, horizon_days, due_date,
         direction, predicted, score, signal_type, entry_price, meta)
    VALUES
        (%(symbol)s, %(skill)s, NULL, %(as_of)s, %(horizon_days)s, %(due_date)s,
         %(direction)s, %(predicted)s, %(score)s, %(signal_type)s,
         %(entry_price)s, %(meta)s::jsonb)
"""


def _insert_rows(conn, rows):
    with conn.cursor() as cur:
        cur.executemany(_INSERT_SQL, rows)
    conn.commit()


def _due_date(as_of):
    return (pd.Timestamp(as_of) + timedelta(days=DUE_OFFSET_DAYS)).date()


# --------------------------------------------------------------------------- #
# predict
# --------------------------------------------------------------------------- #
def cmd_predict():
    conn = get_conn()
    try:
        latest = F.latest_features(conn)

        if latest.empty:
            print("[predict] 沒有近期標的可預測。", file=sys.stderr)
            return

        n_syms = len(latest)
        print(f"[predict] 近期標的數: {n_syms} "
              f"(最新交易日 {latest['ts'].max().date()})")

        # ---- baseline-momentum 已移除（純對照、無實用價值，使用者要求停用）-------- #
        # 原規則：近 20 日報酬符號（ret_20>0 → 續漲）。歷史 analyses 保留、不再新增。

        # ---- ml-logreg：載入模型輸出上漲機率 ----------------------- #
        # docker compose run --rm 每次為全新容器、models/ 未掛載 volume，
        # 故若找不到已存模型則就地重新訓練（自我完備，predict 不依賴前次 train）。
        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, "rb") as f:
                bundle = pickle.load(f)
            print(f"[predict] 載入既有模型 {MODEL_PATH}")
        else:
            print(f"[predict] 無既有模型，就地訓練 ml-logreg ...")
            bundle = _fit_model(conn, tag="predict")
        model = bundle["model"]
        cols = bundle["feature_cols"]

        X = latest[cols].to_numpy(dtype=float)
        proba_up = model.predict_proba(X)[:, 1]  # P(漲)

        ml_rows = []
        for (_, r), p in zip(latest.iterrows(), proba_up):
            up = p >= 0.5
            ml_rows.append({
                "symbol": r["symbol"],
                "skill": "ml-logreg",
                "as_of": r["ts"].date(),
                "horizon_days": HORIZON_DAYS,
                "due_date": _due_date(r["ts"]),
                "direction": "long" if up else "short",
                "predicted": "up" if up else "down",
                "score": round(float(p) * 100, 4),   # 上漲機率(%)
                "signal_type": "ml",
                "entry_price": round(float(r["close"]), 4),
                "meta": '{"model":"ml-logreg","proba_up":%.4f}' % float(p),
            })
        _insert_rows(conn, ml_rows)
        m_up = sum(1 for x in ml_rows if x["predicted"] == "up")
        print(f"[predict] ml-logreg 寫入 {len(ml_rows)} 筆 "
              f"(up={m_up}, down={len(ml_rows) - m_up})")
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("train", "predict"):
        print("用法: python main.py [train|predict]", file=sys.stderr)
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "train":
        cmd_train()
    else:
        cmd_predict()


if __name__ == "__main__":
    main()
