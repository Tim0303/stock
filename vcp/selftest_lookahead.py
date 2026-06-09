"""
selftest_lookahead.py — 無前視自證。

對每一檔 TW，找出所有突破訊號日 d，然後「把 d 之後的資料整段刪掉」重算同一個 d，
驗證 VCPResult 的關鍵欄位（breakout_signal / contraction_count / drawdowns /
durations / pivot_price / last_swing_low / score）完全相同。

若餵入未來資料會改變 d 當天的判定，即代表有前視；此測試確保不會。
"""
from __future__ import annotations
import os, sys
import numpy as np
import psycopg2
import pandas as pd
from vcp_core import detect_vcp_at

def load(conn, sym):
    with conn.cursor() as cur:
        cur.execute("""SELECT ts, open*adj_factor, high*adj_factor, low*adj_factor,
                       close*adj_factor, volume FROM daily_prices WHERE symbol=%s ORDER BY ts""", (sym,))
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["ts","open","high","low","close","volume"])
    for c in ("open","high","low","close","volume"): df[c]=df[c].astype(float)
    df["ts"]=pd.to_datetime(df["ts"])
    return df

def arrs(df):
    return (df["ts"].to_numpy(), df["open"].to_numpy(float), df["high"].to_numpy(float),
            df["low"].to_numpy(float), df["close"].to_numpy(float), df["volume"].to_numpy(float))

def key(r):
    return (r.breakout_signal, r.contraction_count, tuple(r.drawdowns), tuple(r.durations),
            round(r.pivot_price,6) if not np.isnan(r.pivot_price) else None,
            round(r.last_swing_low,6) if not np.isnan(r.last_swing_low) else None,
            round(r.score,6), r.stage2_pass, r.candidate_pass)

conn = psycopg2.connect(os.environ["DATABASE_URL"])
with conn.cursor() as cur:
    cur.execute("SELECT symbol FROM symbols WHERE market='TW' ORDER BY symbol")
    syms=[r[0] for r in cur.fetchall()]

checked=0; mism=0; sample=None
for sym in syms:
    df=load(conn,sym)
    if len(df)<201: continue
    ts,o,h,l,c,v=arrs(df); n=len(c)
    # 找突破日
    sigdays=[d for d in range(200,n) if detect_vcp_at(ts,o,h,l,c,v,d).breakout_signal]
    # 測突破日 + 一些隨機非突破日
    test_days = sigdays[:5] + list(range(200, n, max(1,(n-200)//10)))
    for d in set(test_days):
        if d>=n: continue
        full = detect_vcp_at(ts,o,h,l,c,v,d)
        # 截斷到 d（含），未來資料整段移除
        tts,to_,th,tl,tc,tv = ts[:d+1],o[:d+1],h[:d+1],l[:d+1],c[:d+1],v[:d+1]
        trunc = detect_vcp_at(tts,to_,th,tl,tc,tv,d)
        checked+=1
        if key(full)!=key(trunc):
            mism+=1
            if sample is None:
                sample=(sym,str(df["ts"].iloc[d].date()),key(full),key(trunc))

print(f"[selftest] 檢查 {checked} 個 (symbol,d) 點，不一致 {mism} 個")
if sample:
    print("[selftest] 不一致範例:", sample)
    sys.exit(1)
print("[selftest] PASS：餵入未來資料不改變 d 當天判定 => 無前視偏差")
