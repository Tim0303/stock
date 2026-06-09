"""
vcp_core.py — VCP（波動收縮型態）偵測核心，純函式、無 DB 依賴。

嚴格遵守「無前視偏差（look-ahead bias）」：
  在某一交易日索引 d 上做任何判定（contraction 偵測、收縮遞減、時間壓縮、
  pivot、突破）時，所有輸入只能取自 index <= d 的資料。

  關鍵：swing high/low 的「確認」。
    一個位於 index i 的點要成為 swing high/low，需要其「前後各 swing_window 日」
    都比它低（高）。因此該 swing 點要在 index (i + swing_window) 當天才被「確認」。
    在判定日 d 上，只接受 i + swing_window <= d 的 swing 點 —— 即在 d 當天，
    這個 swing 點的右側 swing_window 根 K 棒都已經出現、極值已成定局，
    不可能再被未來資料推翻。
    => 最近一個（最右）swing low 若其右側 swing_window 日尚未到齊（i+sw > d），
       一律不採用，contraction 不算數。

  pivot_price 取 lookback 內「已確認」swing high 之最大（亦不含 d 之後的 high）。
  突破判定 close > pivot 用「當日 close」（當日可知），pivot 本身不含未來資料。

本模組以 numpy 陣列運算，single source of truth 為 detect_vcp_at()。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# --------------------------------------------------------------------------- #
# 預設參數（規格第 11 節）
# --------------------------------------------------------------------------- #
DEFAULT_PARAMS = {
    "lookback_days": 60,          # VCP 觀察區間
    "swing_window": 3,            # 波段高低點偵測左右 K 數
    "min_contractions": 2,        # 最少收縮次數
    "contraction_ratio": 0.65,    # 後一次回檔需 <= 前一次 * 0.65
    "last_drawdown_max": 0.10,    # 最後一次回檔上限
    "duration_ratio": 0.75,       # 後一次整理時間需 <= 前一次 * 0.75
    "near_pivot_pct": 0.05,       # 距離樞紐點 5% 內（候選）
    "volume_dry_up_ratio": 0.75,  # 10 日量低於 50 日量 75%（量縮）
    "breakout_volume_ratio": 1.30,  # 突破量 >= 50 日均量 1.3 倍
    "ma_trend_lookback": 30,      # MA200 走升比較的回看天數（規格 4.1 T4：20~60）
    "mom_lookback": 120,          # 近 120 日漲幅
    "mom_min": 0.30,              # 強勢股漲幅門檻 30%（建議條件，計分用）
    "horizon_days": 5,
    "stop_loss_pct": 0.07,        # 回測停損：跌破進場價 * (1-0.07)
}


@dataclass
class VCPResult:
    """單一交易日 d 的 VCP 偵測結果。所有欄位僅用 <= d 的資料算出。"""
    has_data: bool = False
    # 趨勢模板
    stage2_pass: bool = False
    close: float = float("nan")
    ma50: float = float("nan")
    ma150: float = float("nan")
    ma200: float = float("nan")
    ma200_rising: bool = False
    mom_120: float = float("nan")      # 近 120 日漲幅
    dist_52w_high: float = float("nan")  # close 距 52 週高 (>=0 表低於高點)
    above_52w_low: float = float("nan")  # close / low_52w - 1
    # 收縮
    contraction_count: int = 0
    drawdowns: list = field(default_factory=list)
    durations: list = field(default_factory=list)
    last_drawdown: float = float("nan")
    drawdown_contracting: bool = False
    time_compression: bool = False
    # 量縮
    vol_ma10: float = float("nan")
    vol_ma50: float = float("nan")
    volume_dry_up: bool = False
    # 樞紐 / 突破
    pivot_price: float = float("nan")
    distance_to_pivot: float = float("nan")   # (pivot-close)/pivot；負=已突破
    near_pivot: bool = False
    breakout: bool = False
    last_swing_low: float = float("nan")      # 最後一次收縮的低點（回測出場用）
    # 評分與通過
    score: float = 0.0
    candidate_pass: bool = False
    breakout_signal: bool = False             # 寫 analyses 的買訊號


def _find_confirmed_swings(high: np.ndarray, low: np.ndarray, d: int,
                           start: int, swing_window: int):
    """
    在 [start, d] 區間內找「已在 d 當天確認」的 swing high / swing low。

    swing high at i: high[i] 為 [i-sw, i+sw] 內嚴格最大（左側 >，右側 >=容忍相等以右側為界）。
    確認條件：i + sw <= d（右側窗口已到齊，極值定局，無前視）。

    回傳兩個 list，元素為 (index, price)，依 index 升冪。
    為避免單根長影線雜訊，用 high/low 判斷（規格允許，必要時可改 close）。
    """
    sw = swing_window
    swing_highs = []
    swing_lows = []
    # 候選中心 i 必須左右各有 sw 根 K，且右側已到齊 (i+sw <= d)
    lo_i = max(start, sw)
    hi_i = d - sw
    for i in range(lo_i, hi_i + 1):
        win_h = high[i - sw:i + sw + 1]
        win_l = low[i - sw:i + sw + 1]
        # swing high：i 為窗口內最大且唯一達到該最大值的最左位置即可
        if high[i] == win_h.max() and high[i] > high[i - sw:i].max(initial=-np.inf):
            swing_highs.append((i, float(high[i])))
        if low[i] == win_l.min() and low[i] < low[i - sw:i].min(initial=np.inf):
            swing_lows.append((i, float(low[i])))
    return swing_highs, swing_lows


def _build_contractions(swing_highs, swing_lows):
    """
    把 swing high -> 後續 swing low 配成 contraction 序列。

    規則：依時間掃描，每個 contraction 由一個 swing high 與其「之後、下一個
    swing high 之前」的最低 swing low 組成（取該段最深回檔）。
    回傳 list of dict: {h_idx, h_price, l_idx, l_price, drawdown, duration}。
    僅形成「高 -> 低」且 drawdown>0 的 contraction。
    """
    contractions = []
    sh = sorted(swing_highs, key=lambda x: x[0])
    sl = sorted(swing_lows, key=lambda x: x[0])
    n = len(sh)
    for k in range(n):
        h_idx, h_price = sh[k]
        next_h_idx = sh[k + 1][0] if k + 1 < n else np.inf
        # 取 (h_idx, next_h_idx) 之間最深的 swing low
        seg = [(li, lp) for (li, lp) in sl if h_idx < li < next_h_idx]
        if not seg:
            continue
        l_idx, l_price = min(seg, key=lambda x: x[1])  # 最低點
        if h_price <= 0 or l_price >= h_price:
            continue
        drawdown = (h_price - l_price) / h_price
        duration = l_idx - h_idx
        contractions.append({
            "h_idx": h_idx, "h_price": h_price,
            "l_idx": l_idx, "l_price": l_price,
            "drawdown": float(drawdown), "duration": int(duration),
        })
    return contractions


def detect_vcp_at(ts, o, h, l, c, v, d: int, params=None) -> VCPResult:
    """
    對「第 d 個交易日」做 VCP 偵測。所有判定僅用 index <= d 的資料。

    參數皆為等長 numpy 陣列（已還原權值），ts 為日期陣列（僅供 debug，不參與判定）。
    回傳 VCPResult。
    """
    P = dict(DEFAULT_PARAMS)
    if params:
        P.update(params)
    res = VCPResult()

    lookback = P["lookback_days"]
    sw = P["swing_window"]

    # 需要足夠歷史算 MA200、52週、120日漲幅
    if d < 200:
        return res
    res.has_data = True

    close_d = float(c[d])
    res.close = close_d

    # ---- 1) 趨勢模板（規格 4.1）只用 <= d 的資料 ---------------------------- #
    ma50 = float(c[d - 49:d + 1].mean())
    ma150 = float(c[d - 149:d + 1].mean())
    ma200 = float(c[d - 199:d + 1].mean())
    res.ma50, res.ma150, res.ma200 = ma50, ma150, ma200

    # MA200 走升：今日 MA200 vs ma_trend_lookback 日前 MA200（皆只用過去資料）
    tl = P["ma_trend_lookback"]
    d_ago = d - tl
    ma200_ago = float(c[d_ago - 199:d_ago + 1].mean()) if d_ago >= 199 else float("nan")
    res.ma200_rising = bool(d_ago >= 199 and ma200 > ma200_ago)

    # 52 週高低（約 252 交易日；不足則用現有）
    w52 = 252
    start52 = max(0, d - w52 + 1)
    high_52w = float(h[start52:d + 1].max())
    low_52w = float(l[start52:d + 1].min())
    res.dist_52w_high = (high_52w - close_d) / high_52w if high_52w > 0 else float("nan")
    res.above_52w_low = close_d / low_52w - 1 if low_52w > 0 else float("nan")

    # 近 120 日漲幅
    ml = P["mom_lookback"]
    base = float(c[d - ml]) if d - ml >= 0 else float("nan")
    res.mom_120 = close_d / base - 1 if base and base > 0 else float("nan")

    # T1..T4 必要條件
    stage2 = (
        close_d > ma200
        and ma150 > ma200
        and ma50 > ma150
        and res.ma200_rising
    )
    res.stage2_pass = bool(stage2)

    # ---- 2) 收縮偵測：lookback 內已確認 swing ------------------------------ #
    start = max(0, d - lookback + 1)
    swing_highs, swing_lows = _find_confirmed_swings(h, l, d, start, sw)
    contractions = _build_contractions(swing_highs, swing_lows)

    res.contraction_count = len(contractions)
    res.drawdowns = [round(x["drawdown"], 4) for x in contractions]
    res.durations = [x["duration"] for x in contractions]

    if contractions:
        res.last_drawdown = float(contractions[-1]["drawdown"])
        res.last_swing_low = float(contractions[-1]["l_price"])

    # 幅度遞減（規格 5.3）：每一步 drawdown_{k} <= drawdown_{k-1} * ratio
    dr_ratio = P["contraction_ratio"]
    dds = [x["drawdown"] for x in contractions]
    drawdown_contracting = len(dds) >= P["min_contractions"]
    for k in range(1, len(dds)):
        if not (dds[k] <= dds[k - 1] * dr_ratio + 1e-12):
            drawdown_contracting = False
            break
    res.drawdown_contracting = bool(drawdown_contracting)

    # 時間壓縮（規格 6.2）：duration_{k} <= duration_{k-1} * ratio
    du_ratio = P["duration_ratio"]
    durs = [x["duration"] for x in contractions]
    time_compression = len(durs) >= P["min_contractions"]
    for k in range(1, len(durs)):
        if durs[k - 1] <= 0 or not (durs[k] <= durs[k - 1] * du_ratio + 1e-9):
            time_compression = False
            break
    res.time_compression = bool(time_compression)

    # ---- 3) 量縮 ---------------------------------------------------------- #
    vol_ma10 = float(v[d - 9:d + 1].mean())
    vol_ma50 = float(v[d - 49:d + 1].mean())
    res.vol_ma10, res.vol_ma50 = vol_ma10, vol_ma50
    res.volume_dry_up = bool(vol_ma50 > 0 and vol_ma10 <= vol_ma50 * P["volume_dry_up_ratio"])

    # ---- 4) 樞紐點：lookback 內已確認 swing high 之最大 -------------------- #
    if swing_highs:
        pivot = max(p for (_, p) in swing_highs)
    else:
        pivot = float("nan")
    res.pivot_price = pivot
    if pivot and pivot > 0 and not np.isnan(pivot):
        res.distance_to_pivot = (pivot - close_d) / pivot
        res.near_pivot = bool(close_d >= pivot * (1 - P["near_pivot_pct"]))
        res.breakout = bool(close_d > pivot)

    # ---- 5) 評分（規格第 10 節）100 分制 ---------------------------------- #
    res.score = _score(res, P)

    # ---- 6) 候選通過（13.1） + 突破買訊號（13.3） ------------------------ #
    res.candidate_pass = bool(
        res.stage2_pass
        and res.contraction_count >= P["min_contractions"]
        and res.drawdown_contracting
        and res.time_compression
        and (not np.isnan(res.last_drawdown)) and res.last_drawdown <= P["last_drawdown_max"]
        and res.near_pivot
    )

    vol_d = float(v[d])
    res.breakout_signal = bool(
        res.candidate_pass
        and (not np.isnan(pivot)) and close_d > pivot
        and vol_ma50 > 0 and vol_d >= vol_ma50 * P["breakout_volume_ratio"]
    )

    return res


def _score(res: VCPResult, P) -> float:
    """規格第 10 節評分：trend30 + 收縮30 + 時間20 + 量縮10 + 接近pivot10。"""
    score = 0.0

    # 趨勢 30：T1~T4 必要條件 18 分，建議條件 T5~T8 各 3 分
    if res.stage2_pass:
        score += 18
        if not np.isnan(res.close) and res.close > res.ma50:
            score += 3
        if not np.isnan(res.mom_120) and res.mom_120 > P["mom_min"]:
            score += 3
        if not np.isnan(res.dist_52w_high) and res.dist_52w_high < 0.25:
            score += 3
        if not np.isnan(res.above_52w_low) and res.above_52w_low >= 0.30:
            score += 3

    # 收縮 30：有 >=2 次收縮給底分，幅度遞減滿分，last_drawdown 越小越好
    nc = res.contraction_count
    if nc >= 2:
        score += 10
        if res.drawdown_contracting:
            score += 12
        if not np.isnan(res.last_drawdown):
            if res.last_drawdown <= 0.05:
                score += 8
            elif res.last_drawdown <= 0.08:
                score += 6
            elif res.last_drawdown <= 0.10:
                score += 4

    # 時間 20
    if res.time_compression:
        score += 20
    elif nc >= 2 and all(
        res.durations[k] <= res.durations[k - 1] for k in range(1, len(res.durations))
    ):
        score += 10  # 寬鬆遞減給一半

    # 量縮 10
    if res.volume_dry_up:
        score += 10
    elif not np.isnan(res.vol_ma10) and not np.isnan(res.vol_ma50) \
            and res.vol_ma50 > 0 and res.vol_ma10 < res.vol_ma50:
        score += 5

    # 接近 pivot 10
    if not np.isnan(res.distance_to_pivot):
        dp = res.distance_to_pivot
        if dp <= 0:            # 已突破，視為最接近
            score += 10
        elif dp <= 0.03:
            score += 10
        elif dp <= 0.05:
            score += 7
        elif dp <= 0.10:
            score += 4

    return round(min(score, 100.0), 4)
