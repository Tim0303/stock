"""
features.py — 從 v_price_indicators 取技術指標，組成 ML 特徵。

設計重點（嚴防未來函數）：
- 特徵列只用「as_of(含)之前」就能算出的技術指標（close 相對均線、bias、量比）。
- 標籤（未來 5 交易日漲跌）由呼叫端用「as_of 之後」的收盤計算，特徵與標籤在時間上嚴格分離。
- 第一版只用技術指標，不依賴任何籌碼表。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# 預測 / 標籤對齊用的水平（與 strat-5-10-20 對齊）
HORIZON_DAYS = 5

# 特徵欄位清單（features.py 與 main.py 共用，確保 train/predict 一致）
FEATURE_COLS = [
    "close_ma5_ratio",   # close / ma5
    "close_ma10_ratio",  # close / ma10
    "close_ma20_ratio",  # close / ma20
    "ma5_ma20_ratio",    # ma5 / ma20（短中期均線排列）
    "bias_ma10",         # 來自 view
    "bias_ma20",         # 來自 view
    "vol_ratio",         # volume / vol_ma5（量能相對）
    "ret_5",             # 近 5 交易日報酬（純歷史）
    "ret_20",            # 近 20 交易日報酬（純歷史，動能）
]

# 從 view 一次撈出的原始欄位
_RAW_SQL = """
    SELECT symbol, ts, close, ma5, ma10, ma20, vol_ma5, volume,
           bias_ma10, bias_ma20, n_window
    FROM v_price_indicators
    WHERE ma20 IS NOT NULL
      AND vol_ma5 IS NOT NULL
      AND n_window >= 20
    ORDER BY symbol, ts
"""


def load_raw(conn) -> pd.DataFrame:
    """讀取全標的、全歷史的技術指標原始資料（已過濾暖機不足列）。"""
    df = pd.read_sql(_RAW_SQL, conn)
    # numeric -> float
    num_cols = ["close", "ma5", "ma10", "ma20", "vol_ma5", "volume",
                "bias_ma10", "bias_ma20"]
    for c in num_cols:
        df[c] = df[c].astype(float)
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def _build_features_inplace(g: pd.DataFrame) -> pd.DataFrame:
    """對單一 symbol（已依 ts 排序）建特徵欄位。只用當列(含)以前資訊。"""
    g = g.copy()
    g["close_ma5_ratio"] = g["close"] / g["ma5"]
    g["close_ma10_ratio"] = g["close"] / g["ma10"]
    g["close_ma20_ratio"] = g["close"] / g["ma20"]
    g["ma5_ma20_ratio"] = g["ma5"] / g["ma20"]
    # bias_ma10 / bias_ma20 直接沿用 view
    g["vol_ratio"] = g["volume"] / g["vol_ma5"].replace(0, np.nan)
    # 純歷史報酬（shift 取過去收盤；不碰未來）
    g["ret_5"] = g["close"] / g["close"].shift(5) - 1.0
    g["ret_20"] = g["close"] / g["close"].shift(20) - 1.0
    return g


def build_feature_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    回傳含 FEATURE_COLS + (symbol, ts, close) 的 DataFrame。
    每列代表「在該 ts（as_of）收盤後可得」的特徵。
    """
    parts = []
    for _, g in df.groupby("symbol", sort=False):
        g = g.sort_values("ts")
        parts.append(_build_features_inplace(g))
    out = pd.concat(parts, ignore_index=True)
    return out


def add_label(df_feat: pd.DataFrame, horizon: int = HORIZON_DAYS) -> pd.DataFrame:
    """
    加上標籤 y：未來 horizon 個交易日後收盤是否高於當日（1=漲, 0=跌/平）。
    使用 shift(-horizon)，僅用於 train。predict 不呼叫此函式。
    """
    parts = []
    for _, g in df_feat.groupby("symbol", sort=False):
        g = g.sort_values("ts").copy()
        future_close = g["close"].shift(-horizon)
        g["future_close"] = future_close
        g["y"] = (future_close > g["close"]).astype("float")
        # 未來收盤缺值（最後 horizon 列）標籤無效，設 NaN 之後 dropna
        g.loc[future_close.isna(), "y"] = np.nan
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def training_xy(conn, horizon: int = HORIZON_DAYS):
    """
    產生訓練用 (X, y)。
    - 特徵：as_of 收盤後可得。
    - 標籤：as_of 之後 horizon 交易日。
    - dropna 後特徵與標籤都齊全，時間嚴格分離。
    """
    raw = load_raw(conn)
    feat = build_feature_frame(raw)
    labeled = add_label(feat, horizon=horizon)
    # 任何除以 0 造成的 inf 一律視為缺值
    labeled[FEATURE_COLS] = labeled[FEATURE_COLS].replace([np.inf, -np.inf], np.nan)
    cols = FEATURE_COLS + ["y"]
    clean = labeled.dropna(subset=cols)
    X = clean[FEATURE_COLS].to_numpy(dtype=float)
    y = clean["y"].to_numpy(dtype=int)
    return X, y, clean


def latest_features(conn):
    """
    取每檔「近期標的」最新交易日的特徵（給 predict 用，不含標籤/未來資訊）。
    近期標的定義：該 symbol 最新 ts >= 全表 max(ts) - 5 天。
    回傳 DataFrame（含 FEATURE_COLS + symbol, ts, close），每檔一列。
    """
    raw = load_raw(conn)
    feat = build_feature_frame(raw)

    # 全表最新交易日
    global_max = feat["ts"].max()
    cutoff = global_max - pd.Timedelta(days=5)

    # 每檔最新一列
    idx = feat.groupby("symbol")["ts"].idxmax()
    latest = feat.loc[idx].copy()

    # 只留近期標的（剔除殭屍股）
    latest = latest[latest["ts"] >= cutoff]
    # inf -> nan，特徵需齊全
    latest[FEATURE_COLS] = latest[FEATURE_COLS].replace([np.inf, -np.inf], np.nan)
    latest = latest.dropna(subset=FEATURE_COLS)
    return latest.reset_index(drop=True)
