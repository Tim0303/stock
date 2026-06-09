"""show_example.py — 列出一檔的 VCP 突破實例細節（供報告佐證）。"""
from __future__ import annotations
import os, sys
import numpy as np, pandas as pd, psycopg2
from vcp_core import detect_vcp_at

sym = sys.argv[1] if len(sys.argv) > 1 else "2382.TW"
conn = psycopg2.connect(os.environ["DATABASE_URL"])
with conn.cursor() as cur:
    cur.execute("""SELECT ts, open*adj_factor, high*adj_factor, low*adj_factor,
                   close*adj_factor, volume FROM daily_prices WHERE symbol=%s ORDER BY ts""", (sym,))
    rows = cur.fetchall()
df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume"])
for c in ("open","high","low","close","volume"): df[c]=df[c].astype(float)
df["ts"]=pd.to_datetime(df["ts"])
ts=df["ts"].to_numpy(); o=df["open"].to_numpy(float); h=df["high"].to_numpy(float)
l=df["low"].to_numpy(float); c=df["close"].to_numpy(float); v=df["volume"].to_numpy(float)

# 找評分最高、收縮 >=3 的突破日做範例
best=None
for d in range(200,len(c)):
    r=detect_vcp_at(ts,o,h,l,c,v,d)
    if r.breakout_signal and r.contraction_count>=3:
        if best is None or r.score>best[1].score:
            best=(d,r)
if best is None:
    for d in range(200,len(c)):
        r=detect_vcp_at(ts,o,h,l,c,v,d)
        if r.breakout_signal and (best is None or r.score>best[1].score):
            best=(d,r)
d,r=best
print(f"=== {sym} VCP 突破實例 ===")
print(f"突破日           : {pd.Timestamp(ts[d]).date()}  (index {d})")
print(f"stage2_pass      : {r.stage2_pass}")
print(f"close/MA50/150/200: {r.close:.2f} / {r.ma50:.2f} / {r.ma150:.2f} / {r.ma200:.2f}")
print(f"MA200 走升       : {r.ma200_rising}")
print(f"近120日漲幅      : {r.mom_120:.2%}")
print(f"距52週高 / 高於52週低: {r.dist_52w_high:.2%} / {r.above_52w_low:.2%}")
print(f"收縮次數         : {r.contraction_count}")
print(f"各次回檔(drawdowns): {[f'{x:.1%}' for x in r.drawdowns]}")
print(f"各次天數(durations): {r.durations}")
print(f"last_drawdown    : {r.last_drawdown:.2%}")
print(f"幅度遞減/時間壓縮 : {r.drawdown_contracting} / {r.time_compression}")
print(f"量縮 vol_ma10/50 : {r.volume_dry_up}  ({r.vol_ma10:.0f} / {r.vol_ma50:.0f})")
print(f"pivot / 距pivot  : {r.pivot_price:.2f} / {r.distance_to_pivot:.2%}")
print(f"突破日量 / 1.3*MA50: {v[d]:.0f} / {r.vol_ma50*1.3:.0f}")
print(f"score            : {r.score}")
print(f"breakout_signal  : {r.breakout_signal}")
