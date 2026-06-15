"""
features.py — ML 特徵 + 標籤。

設計（嚴防未來函數）：
- 特徵列只用「as_of(含)之前」可得的技術指標。
- ★標籤改用「bracket 出場結果」(與平台 evaluate_due_predictions 同口徑：壓力目標/−8%停損/40交易日)，
  讓 ml-logreg 的學習目標 = 它被評分的目標（原本標籤是 5 日漲跌、與 bracket 評分錯位）。
- 特徵與標籤在時間上嚴格分離（標籤用 as_of 之後的價格，且 train 才需要）。

特徵（14 維，含實證特徵）：
  均線/動能：close/ma5,10,20、ma5/ma20、bias_ma10/20、vol_ratio(量/5日均量)、ret_5、ret_20
  實證新增：vol_ratio_50(情境量=量/50日均量)、dist_res60(距60日壓力)、dist_sup60(距60日支撐)、
            vol_contraction(波動收縮=std10/std50，VCP式)、breadth(大盤寬度)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HORIZON_DAYS = 5          # 沿用（meta/相容用）；標籤實際走 bracket 40 日
BRACKET_MAXHOLD = 40
BRACKET_COST = 0.006

FEATURE_COLS = [
    "close_ma5_ratio", "close_ma10_ratio", "close_ma20_ratio", "ma5_ma20_ratio",
    "bias_ma10", "bias_ma20",
    "vol_ratio",        # volume / vol_ma5（5 日均量）
    "vol_ratio_50",     # volume / 50 日均量（情境量）
    "ret_5", "ret_20",
    "dist_res60",       # (60 日前高 − close)/close（越小越接近壓力）
    "dist_sup60",       # (close − 60 日前低)/close（越小越接近支撐）
    "vol_contraction",  # std(ret,10)/std(ret,50)（<1=波動收縮，VCP 式）
    "breadth",          # 大盤寬度（% 站上 20MA，0~1）
    # ★籌碼特徵（2026-06-15 承布林突破甜蜜點研究：法人吸貨是最強輸贏分水嶺）
    "chip_f5",          # 前5日外資淨買 / 20日均量（外資吸貨強度）
    "chip_t5",          # 前5日三大法人淨買 / 20日均量（法人吸貨強度）
    "chip_t20",         # 前20日三大法人淨買 / 20日均量（中期吸貨）
    # ★布林帶寬/位置（帶寬擴張＝真突破）
    "bb_bw_ratio",      # 帶寬(4σ/ma20) / 5日前帶寬（擴張倍數）
    "bb_pctb",          # %B＝(close−下軌)/(上軌−下軌)（布林相對位置）
]

# 原始資料：技術指標(view) + 還原高低(算壓力/支撐) ；volume 用 view 的（與 vol_ma5 同口徑）
_RAW_SQL = """
    SELECT v.symbol, v.ts, v.close, v.ma5, v.ma10, v.ma20, v.vol_ma5, v.volume,
           v.bias_ma10, v.bias_ma20, v.n_window,
           d.high*d.adj_factor AS high_adj, d.low*d.adj_factor AS low_adj
    FROM v_price_indicators v
    JOIN daily_prices d ON d.symbol=v.symbol AND d.ts=v.ts
    WHERE v.ma20 IS NOT NULL AND v.vol_ma5 IS NOT NULL AND v.n_window >= 20
    ORDER BY v.symbol, v.ts
"""

_BREADTH_SQL = "SELECT ts, breadth_pct FROM v_market_regime"
_CHIP_SQL = "SELECT symbol, ts, foreign_net, total_net FROM chip_institutional"


def _load_chip(conn) -> pd.DataFrame:
    c = pd.read_sql(_CHIP_SQL, conn)
    c["ts"] = pd.to_datetime(c["ts"])
    for k in ("foreign_net", "total_net"):
        c[k] = c[k].astype(float)
    return c


def load_raw(conn) -> pd.DataFrame:
    df = pd.read_sql(_RAW_SQL, conn)
    num = ["close", "ma5", "ma10", "ma20", "vol_ma5", "volume",
           "bias_ma10", "bias_ma20", "high_adj", "low_adj"]
    for c in num:
        df[c] = df[c].astype(float)
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def _load_breadth(conn) -> pd.DataFrame:
    b = pd.read_sql(_BREADTH_SQL, conn)
    b["ts"] = pd.to_datetime(b["ts"])
    b["breadth"] = b["breadth_pct"].astype(float) / 100.0
    return b[["ts", "breadth"]]


def _build_features_inplace(g: pd.DataFrame) -> pd.DataFrame:
    """單一 symbol（依 ts 排序）建特徵；只用當列(含)以前資訊。"""
    g = g.sort_values("ts").copy()
    g["close_ma5_ratio"] = g["close"] / g["ma5"]
    g["close_ma10_ratio"] = g["close"] / g["ma10"]
    g["close_ma20_ratio"] = g["close"] / g["ma20"]
    g["ma5_ma20_ratio"] = g["ma5"] / g["ma20"]
    g["vol_ratio"] = g["volume"] / g["vol_ma5"].replace(0, np.nan)
    g["vol_ratio_50"] = g["volume"] / g["volume"].rolling(50, min_periods=30).mean().replace(0, np.nan)
    g["ret_5"] = g["close"] / g["close"].shift(5) - 1.0
    g["ret_20"] = g["close"] / g["close"].shift(20) - 1.0
    # 壓力/支撐：用「前 60 日(不含當日)」的還原高/低
    res60 = g["high_adj"].rolling(60, min_periods=40).max().shift(1)
    sup60 = g["low_adj"].rolling(60, min_periods=40).min().shift(1)
    g["dist_res60"] = (res60 - g["close"]) / g["close"]
    g["dist_sup60"] = (g["close"] - sup60) / g["close"]
    # 波動收縮（VCP 式）：近 10 日報酬波動 / 近 50 日報酬波動
    ret1 = g["close"].pct_change()
    std10 = ret1.rolling(10, min_periods=8).std()
    std50 = ret1.rolling(50, min_periods=30).std().replace(0, np.nan)
    g["vol_contraction"] = std10 / std50
    # 籌碼：法人淨買累計 / 20日均量（缺資料的日子視為 0 淨流；用「截至當日(含)」資訊）
    volma20 = g["volume"].rolling(20, min_periods=15).mean().replace(0, np.nan)
    fn = g["foreign_net"].fillna(0.0) if "foreign_net" in g else 0.0
    tn = g["total_net"].fillna(0.0) if "total_net" in g else 0.0
    g["chip_f5"] = (fn.rolling(5, min_periods=1).sum() / volma20) if "foreign_net" in g else np.nan
    g["chip_t5"] = (tn.rolling(5, min_periods=1).sum() / volma20) if "total_net" in g else np.nan
    g["chip_t20"] = (tn.rolling(20, min_periods=5).sum() / volma20) if "total_net" in g else np.nan
    # 布林帶寬擴張 + %B（用 view 的 close 算，比率 scale-invariant）
    std20 = g["close"].rolling(20, min_periods=20).std(ddof=0)
    bw = 4.0 * std20 / g["ma20"]
    g["bb_bw_ratio"] = bw / bw.shift(5).replace(0, np.nan)
    upper = g["ma20"] + 2.0 * std20
    lower = g["ma20"] - 2.0 * std20
    g["bb_pctb"] = (g["close"] - lower) / (upper - lower).replace(0, np.nan)
    return g


def build_feature_frame(df: pd.DataFrame, conn=None) -> pd.DataFrame:
    # 先把籌碼(三大法人)併進每檔逐日資料，供 _build_features_inplace 算滾動吸貨強度
    if conn is not None:
        df = df.merge(_load_chip(conn), on=["symbol", "ts"], how="left")
    parts = [_build_features_inplace(g) for _, g in df.groupby("symbol", sort=False)]
    out = pd.concat(parts, ignore_index=True)
    if conn is not None:
        out = out.merge(_load_breadth(conn), on="ts", how="left")
    else:
        out["breadth"] = np.nan
    return out


# --------------------------------------------------------------------------- #
# 標籤：bracket 出場結果（與 evaluate_due_predictions 同口徑）
# --------------------------------------------------------------------------- #
_LABEL_BUILD = """
CREATE TEMP TABLE _mlpx ON COMMIT DROP AS
  SELECT symbol, ts, high*adj_factor AS hi, low*adj_factor AS lo, close*adj_factor AS cl,
         row_number() OVER (PARTITION BY symbol ORDER BY ts) AS rn
  FROM daily_prices WHERE close>0;
CREATE INDEX ON _mlpx(symbol, rn);
CREATE INDEX ON _mlpx(symbol, ts);
"""

_LABEL_SQL = """
SELECT e.symbol, e.ts, (x.net_ret > 0)::int AS y, x.net_ret
FROM _mlpx e
JOIN v_trade_targets t ON t.symbol=e.symbol AND t.ts=e.ts
CROSS JOIN LATERAL (
  WITH fwd AS (
    SELECT i.rn, i.cl, (i.lo<=t.stop_price) AS sl, (i.hi>=t.target_price) AS tp
    FROM _mlpx i WHERE i.symbol=e.symbol AND i.rn>e.rn AND i.rn<=e.rn+{maxhold}
  ),
  fh AS (SELECT CASE WHEN sl THEN t.stop_price ELSE t.target_price END AS exit_price
         FROM fwd WHERE sl OR tp ORDER BY rn LIMIT 1),
  mt AS (SELECT cl AS exit_price FROM _mlpx WHERE symbol=e.symbol AND rn=e.rn+{maxhold})
  SELECT round((exit_price/e.cl - 1) - {cost}, 5) AS net_ret
  FROM (SELECT exit_price FROM fh
        UNION ALL SELECT exit_price FROM mt WHERE NOT EXISTS (SELECT 1 FROM fh) LIMIT 1) z
) x
""".format(maxhold=BRACKET_MAXHOLD, cost=BRACKET_COST)


def load_bracket_labels(conn) -> pd.DataFrame:
    """回傳 (symbol, ts, y, net_ret)；仍未結算(近 40 日)者無列。"""
    with conn.cursor() as cur:
        cur.execute(_LABEL_BUILD)
    lab = pd.read_sql(_LABEL_SQL, conn)
    conn.rollback()   # 丟棄 temp 表（不留痕跡）
    lab["ts"] = pd.to_datetime(lab["ts"])
    return lab


def training_frame(conn, horizon: int = HORIZON_DAYS):
    """產生訓練用 DataFrame（含 FEATURE_COLS + symbol, ts, close, y, net_ret）。"""
    raw = load_raw(conn)
    feat = build_feature_frame(raw, conn=conn)
    lab = load_bracket_labels(conn)
    df = feat.merge(lab, on=["symbol", "ts"], how="inner")
    df[FEATURE_COLS] = df[FEATURE_COLS].replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=FEATURE_COLS + ["y"])
    return df.reset_index(drop=True)


def latest_features(conn):
    """每檔近期標的最新交易日的特徵（predict 用，無標籤）。"""
    raw = load_raw(conn)
    feat = build_feature_frame(raw, conn=conn)
    global_max = feat["ts"].max()
    cutoff = global_max - pd.Timedelta(days=5)
    idx = feat.groupby("symbol")["ts"].idxmax()
    latest = feat.loc[idx].copy()
    latest = latest[latest["ts"] >= cutoff]
    latest[FEATURE_COLS] = latest[FEATURE_COLS].replace([np.inf, -np.inf], np.nan)
    latest = latest.dropna(subset=FEATURE_COLS)
    return latest.reset_index(drop=True)


# =========================================================================== #
# 突破成功率模型（ml-logreg 新身分，2026-06-15）
#   只在「布林突破訊號母體」上學：特徵=籌碼(法人吸貨)+布林(帶寬/%B)+量價，
#   標籤=這筆突破 20MA 出場賺否。GBDT 原生吃 NaN，故特徵不 dropna。
#   訊號偵測直接複用線上 v_bb_breakout(is_signal)，與 strat-bb-breakout 完全一致。
# =========================================================================== #
BB_FEATURE_COLS = ["pre_f", "pre_t", "pre_tr", "pre_mc", "pb", "bwr", "vr", "ma5slope", "distu"]
BB_THRESHOLD = 0.40          # 報告 walk-forward 驗證採用門檻
BB_EXCLUDE = ("8422.TW",)    # 減資未還原

_BB_PANEL_SQL = """
  SELECT symbol, ts, open*adj_factor AS o, high*adj_factor AS hi, low*adj_factor AS lo,
         close*adj_factor AS cl, volume
  FROM daily_prices
  WHERE close>0 AND open IS NOT NULL AND high IS NOT NULL AND low IS NOT NULL AND adj_factor IS NOT NULL
  ORDER BY symbol, ts
"""
_BB_SIG_SQL = "SELECT symbol, ts, vol_ratio, bw_ratio FROM v_bb_breakout WHERE is_signal"
_BB_CHIP_SQL = "SELECT symbol, ts, foreign_net, trust_net, total_net FROM chip_institutional"
_BB_MARGIN_SQL = "SELECT symbol, ts, margin_change FROM chip_margin"


def _bb_panels(conn):
    df = pd.read_sql(_BB_PANEL_SQL, conn)
    df["ts"] = pd.to_datetime(df["ts"])
    P = {}
    for s, g in df.groupby("symbol", sort=False):
        g = g.sort_values("ts")
        cl = g["cl"].to_numpy(float); vol = g["volume"].to_numpy(float)
        P[s] = {
            "ts": list(g["ts"]),
            "o": g["o"].to_numpy(float), "cl": cl, "vol": vol,
            "ma5": pd.Series(cl).rolling(5, min_periods=5).mean().to_numpy(),
            "ma20": pd.Series(cl).rolling(20, min_periods=20).mean().to_numpy(),
            "std20": pd.Series(cl).rolling(20, min_periods=20).std(ddof=0).to_numpy(),
            "volma20": pd.Series(vol).rolling(20, min_periods=15).mean().to_numpy(),
            "idx": {t: i for i, t in enumerate(g["ts"])},
        }
    return P


def breakout_frame(conn, need_label: bool = True) -> pd.DataFrame:
    """所有布林突破訊號的籌碼+布林特徵（need_label 時附 20MA 出場 ret/win）。"""
    P = _bb_panels(conn)
    sigs = pd.read_sql(_BB_SIG_SQL, conn); sigs["ts"] = pd.to_datetime(sigs["ts"])
    chip = pd.read_sql(_BB_CHIP_SQL, conn); chip["ts"] = pd.to_datetime(chip["ts"])
    cdict = {(r.symbol, r.ts): (float(r.foreign_net or 0), float(r.trust_net or 0), float(r.total_net or 0))
             for r in chip.itertuples()}
    marg = pd.read_sql(_BB_MARGIN_SQL, conn); marg["ts"] = pd.to_datetime(marg["ts"])
    mdict = {(r.symbol, r.ts): float(r.margin_change or 0) for r in marg.itertuples()}

    out = []
    for r in sigs.itertuples():
        sym = r.symbol
        if sym in BB_EXCLUDE:
            continue
        pk = P.get(sym)
        if not pk:
            continue
        j = pk["idx"].get(r.ts)
        if j is None or j < 20:
            continue
        cl = pk["cl"][j]; ma = pk["ma20"][j]; std = pk["std20"][j]; vma = pk["volma20"][j]
        if np.isnan(ma) or np.isnan(std) or std <= 0 or np.isnan(vma) or vma <= 0:
            continue
        upper = ma + 2 * std; lower = ma - 2 * std
        pb = (cl - lower) / (upper - lower) if upper > lower else np.nan
        ma5p = pk["ma5"][j - 5] if j >= 5 else np.nan
        ma5slope = (pk["ma5"][j] - ma5p) / ma5p if (not np.isnan(ma5p) and ma5p > 0) else np.nan
        distu = (cl - upper) / cl
        N = len(pk["ts"])

        def csum(a, b, which):
            tot = 0.0; has = False
            for k in range(j + a, j + b + 1):
                if 0 <= k < N:
                    c = cdict.get((sym, pk["ts"][k]))
                    if c is not None:
                        tot += c[which]; has = True
            return tot if has else np.nan

        def msum(a, b):
            tot = 0.0; has = False
            for k in range(j + a, j + b + 1):
                if 0 <= k < N:
                    m = mdict.get((sym, pk["ts"][k]))
                    if m is not None:
                        tot += m; has = True
            return tot if has else np.nan

        row = dict(symbol=sym, ts=r.ts, entry_close=float(cl),
                   vr=float(r.vol_ratio) if r.vol_ratio is not None else np.nan,
                   bwr=float(r.bw_ratio) if r.bw_ratio is not None else np.nan,
                   pb=pb, ma5slope=ma5slope, distu=distu,
                   pre_f=csum(-5, 0, 0) / vma, pre_tr=csum(-5, 0, 1) / vma,
                   pre_t=csum(-5, 0, 2) / vma, pre_mc=msum(-5, 0) / vma)
        if need_label:
            ej = j + 1; ret = None
            if ej < N and pk["o"][ej] > 0:
                eo = pk["o"][ej]
                for k in range(ej, N):
                    m2 = pk["ma20"][k]
                    if not np.isnan(m2) and pk["cl"][k] < m2:
                        if k + 1 < N:
                            ret = float(pk["o"][k + 1]) / eo - 1 - 0.006
                        break
            row["ret"] = ret
            row["win"] = (np.nan if ret is None else (1 if ret > 0 else 0))
        out.append(row)
    return pd.DataFrame(out).replace([np.inf, -np.inf], np.nan)


def breakout_latest(conn, days: int = 6) -> pd.DataFrame:
    """近 days 日內的突破訊號特徵（predict 用，無標籤）。"""
    df = breakout_frame(conn, need_label=False)
    if df.empty:
        return df
    gmax = df["ts"].max()
    return df[df["ts"] >= gmax - pd.Timedelta(days=days)].reset_index(drop=True)
