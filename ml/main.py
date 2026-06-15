"""
main.py — ML 分析師（ml-logreg）進入點。

★2026-06-15 改身分為「突破成功率模型」：ml-logreg 不再對全市場打分，而是
  **只在布林突破訊號母體上學**（特徵=籌碼法人吸貨+布林帶寬/%B+量價，標籤=該突破 20MA 出場賺否），
  輸出「這個突破會成功的機率」，proba≥0.40 才標 up 進 analyses。等於「模型過濾後的突破」分析師，
  與 strat-bb-breakout(全部突破都進) 同台、各自風險/報酬讓使用者自評。strat-bb-breakout 不受影響。
  walk-forward 實證(報告 布林突破_成功率模型_…)：勝率43%/14x/回撤18%，三項勝基準與手刻C3。

子命令：
  train    : 在突破訊號母體訓 GBDT，時間切分 OOS 驗證，門檻 0.40，存 models/logreg.pkl。
  predict  : 對近期突破訊號打分；只在 proba≥0.40 標 predicted='up' 寫入 analyses(skill=ml-logreg)。

優化重點：
  1. 標籤用 bracket 出場（壓力目標/−8%/40日）→ 學習目標 = 被評分目標（非 5 日漲跌）。
  2. 加實證特徵：情境量(量/50日均量)、距壓力/距支撐、波動收縮、大盤寬度。
  3. 時間切分 OOS 驗證 + 機率門檻選股（取代 in-sample + 全標 up）。
  4. ★模型升級 GBDT（2026-06-15）：非線性 + 特徵交互，OOS AUC 0.57→0.62，
     把量能/動能/波動收縮/大盤寬度等線性模型用不到的實證特徵靠交互救活；
     門檻 floor 拉高到測試 1%（避免薄樣本雜訊桶）。檔名仍沿用 logreg.pkl（相容 volume）。

契約：只 INSERT 合 analyses schema 的列，不改表、不刪資料。
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
HORIZON_DAYS = F.HORIZON_DAYS
DUE_OFFSET_DAYS = round(F.BRACKET_MAXHOLD * 1.4)   # bracket 40 日 → due ~56 日曆日
THR_GRID = [0.55, 0.60, 0.65, 0.70, 0.75]


def get_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("[error] DATABASE_URL 未設定", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(url)


def _new_model():
    # GBDT（梯度提升決策樹）取代 LogisticRegression：非線性 + 特徵交互，
    # 能把量能/動能/波動收縮/大盤寬度等「LR 判死刑」的實證特徵靠交互救活。
    # 防過擬合：淺樹(depth3) + 小學習率 + L2 + min_samples_leaf + early stopping。
    # 樹模型對尺度免疫 → 不需 StandardScaler。
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(
        max_depth=3, learning_rate=0.05, max_iter=400,
        l2_regularization=1.0, min_samples_leaf=40,
        early_stopping=True, validation_fraction=0.15, random_state=42,
    )


def _fit_bundle(conn, tag="train"):
    """突破成功率模型：在 bb 突破訊號母體上學(籌碼+布林→20MA出場賺否)，時間切分 OOS 驗證。
    GBDT 原生吃 NaN，故特徵不丟。門檻固定 0.40（報告 walk-forward 驗證採用）。"""
    from sklearn.metrics import roc_auc_score

    cols = F.BB_FEATURE_COLS
    df = F.breakout_frame(conn).dropna(subset=["win"]).reset_index(drop=True)
    n = len(df)
    if n < 300:
        print(f"[error] 突破訊號訓練樣本太少 ({n})，中止。", file=sys.stderr)
        sys.exit(1)
    df["win"] = df["win"].astype(int)
    base = df["win"].mean()
    print(f"[{tag}] 突破訊號 {n}（標籤=20MA出場賺否；勝率基準 base={base:.3f}）"
          f"｜特徵 {len(cols)}: {', '.join(cols)}")

    # 時間切分：最後 ~2 年當 OOS 測試
    cutoff = df["ts"].max() - pd.Timedelta(days=730)
    tr, te = df[df["ts"] < cutoff], df[df["ts"] >= cutoff]
    if len(te) < 60:
        cutoff = df["ts"].quantile(0.8)
        tr, te = df[df["ts"] < cutoff], df[df["ts"] >= cutoff]
    Xtr, ytr = tr[cols].to_numpy(float), tr["win"].to_numpy(int)
    Xte, yte = te[cols].to_numpy(float), te["win"].to_numpy(int)

    model = _new_model()
    model.fit(Xtr, ytr)
    p_te = model.predict_proba(Xte)[:, 1]
    base_te = yte.mean()
    try:
        auc = roc_auc_score(yte, p_te)
    except ValueError:
        auc = float("nan")
    thr = F.BB_THRESHOLD
    sel = p_te >= thr
    nb = int(sel.sum())
    win_sel = yte[sel].mean() if nb else float("nan")
    ret_sel = te.loc[sel, "ret"].mean() * 100 if nb else float("nan")
    print(f"[{tag}] === OOS（{cutoff.date()} 後 {len(te)} 筆，base={base_te:.3f}）AUC={auc:.4f} ===")
    print(f"[{tag}] 門檻 {thr:.2f}：選 {nb} 筆、命中率 {win_sel:.3f}(vs基準 {base_te:.3f})、平均報酬 {ret_sel:+.2f}%")

    # 特徵重要性（OOS permutation importance）
    from sklearn.inspection import permutation_importance
    pim = permutation_importance(model, Xte, yte, n_repeats=5, random_state=42, scoring="roc_auc")
    order = np.argsort(-pim.importances_mean)
    tops = ", ".join(f"{cols[i]}={pim.importances_mean[i]:+.4f}" for i in order[:6])
    print(f"[{tag}] 主要特徵重要性(OOS AUC 掉幅): {tops}")

    # 最終模型：全資料重訓
    final = _new_model()
    final.fit(df[cols].to_numpy(float), df["win"].to_numpy(int))
    return {"model": final, "feature_cols": cols, "threshold": float(thr),
            "horizon": HORIZON_DAYS, "base_rate": float(base), "oos_auc": float(auc),
            "kind": "breakout-success"}


def cmd_train():
    conn = get_conn()
    try:
        bundle = _fit_bundle(conn, tag="train")
    finally:
        conn.close()
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(bundle, f)
    print(f"[train] 模型已存: {MODEL_PATH}")


_INSERT_SQL = """
    INSERT INTO analyses
        (symbol, skill, skill_id, as_of, horizon_days, due_date,
         direction, predicted, score, signal_type, entry_price, meta)
    VALUES
        (%(symbol)s, %(skill)s, NULL, %(as_of)s, %(horizon_days)s, %(due_date)s,
         %(direction)s, %(predicted)s, %(score)s, %(signal_type)s,
         %(entry_price)s, %(meta)s::jsonb)
"""


def _due_date(as_of):
    return (pd.Timestamp(as_of) + timedelta(days=DUE_OFFSET_DAYS)).date()


def cmd_predict():
    conn = get_conn()
    try:
        latest = F.breakout_latest(conn)
        if latest.empty:
            print("[predict] 近期無布林突破訊號，ml-logreg(突破成功率) 不出手。")
            return

        if os.path.exists(MODEL_PATH):
            with open(MODEL_PATH, "rb") as f:
                bundle = pickle.load(f)
            print(f"[predict] 載入既有模型 {MODEL_PATH}（kind={bundle.get('kind')}、門檻 "
                  f"{bundle.get('threshold', F.BB_THRESHOLD):.2f}）")
        else:
            print("[predict] 無既有模型，就地訓練 ...")
            bundle = _fit_bundle(conn, tag="predict")
        model, cols = bundle["model"], bundle["feature_cols"]
        thr = float(bundle.get("threshold", F.BB_THRESHOLD))

        # 去重：已寫過的 (symbol, as_of) ml-logreg live 預測跳過
        with conn.cursor() as cur:
            cur.execute("""SELECT symbol, as_of FROM analyses
                           WHERE skill='ml-logreg' AND (meta->>'backtest') IS DISTINCT FROM 'true'""")
            existing = {(s, d) for s, d in cur.fetchall()}

        proba = model.predict_proba(latest[cols].to_numpy(float))[:, 1]
        rows = []
        for (_, r), p in zip(latest.iterrows(), proba):
            if p < thr:                              # 只記錄模型看好(可進場)的突破
                continue
            as_of = r["ts"].date()
            if (r["symbol"], as_of) in existing:
                continue
            rows.append({
                "symbol": r["symbol"], "skill": "ml-logreg",
                "as_of": as_of, "horizon_days": HORIZON_DAYS, "due_date": _due_date(r["ts"]),
                "direction": "long", "predicted": "up",
                "score": round(float(p) * 100, 4), "signal_type": "ml-bb",
                "entry_price": round(float(r["entry_close"]), 4),
                "meta": '{"model":"breakout-success","proba_up":%.4f,"threshold":%.2f}' % (float(p), thr),
            })
        if not rows:
            print(f"[predict] 近期 {len(latest)} 個突破訊號，無 proba≥{thr:.2f} 的新進場。")
            return
        with conn.cursor() as cur:
            cur.executemany(_INSERT_SQL, rows)
        conn.commit()
        print(f"[predict] ml-logreg(突破成功率) 寫入 {len(rows)} 筆 up"
              f"（近期突破 {len(latest)}、門檻 {thr:.2f}）")
    finally:
        conn.close()


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("train", "predict"):
        print("用法: python main.py [train|predict]", file=sys.stderr)
        sys.exit(2)
    cmd_train() if sys.argv[1] == "train" else cmd_predict()


if __name__ == "__main__":
    main()
