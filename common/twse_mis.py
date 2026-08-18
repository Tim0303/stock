"""TWSE MIS 即時報價 — loader 與 api 共用（單一收口點）。

歷史教訓：這段邏輯原本在 `loader/main.py` 與 `api/app.py` 各有一份複製，
交易日防呆只補在 loader 那份，導致非交易日按儀表板「↻ 重新整理」時，
MIS 回傳的上一交易日殘影被寫成當日 K 線（2026-08-09 週日憑空長出 301 檔假列）。
**盤中報價與交易日判斷的任何修改，一律只改這個檔案。**

用途：13:10 尾盤掃描 / 儀表板手動重整，抓現價當今日暫定 OHLC 寫入 daily_prices，
讓策略 view 即時算今日訊號；15:00 正式收盤那班會以 FinMind 官方收盤 UPSERT 覆蓋同一列。
adj_factor 維持 1.0（最新一筆=1.0 的還原權值慣例）。
"""
import time
from datetime import date, datetime, timedelta, timezone

import requests

MIS_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
# 台北時區（台灣無夏令時，固定 UTC+8）。容器預設跑 UTC，若用 date.today() 取「今天」，
# 台北 00:00–08:00 的請求會算成前一天 → 暫定盤寫錯日期。交易日判斷一律以此為準。
TPE = timezone(timedelta(hours=8))
BATCH = 50      # MIS 單次查詢的 ex_ch 檔數
PAUSE = 0.4     # 批次間隔（秒），對 MIS 端點友善

# rows 欄位順序＝此 SQL 的 VALUES 順序，兩者必須一起改
UPSERT_SQL = """
    INSERT INTO daily_prices (symbol, ts, open, high, low, close, volume, adj_factor)
    VALUES %s
    ON CONFLICT (symbol, ts) DO UPDATE SET
        open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
        close = EXCLUDED.close, volume = EXCLUDED.volume
"""


def today_tpe() -> date:
    """今日（台北）。不要用 date.today()——容器跑 UTC 會在台北凌晨算成前一天。"""
    return datetime.now(TPE).date()


def to_channel(symbol: str) -> str:
    """`2330.TW` → `tse_2330.tw`；`1815.TWO` → `otc_1815.tw`。"""
    code = symbol.split(".")[0]
    return ("otc_" if symbol.endswith(".TWO") else "tse_") + code + ".tw"


def mis_num(x):
    """MIS 欄位轉正數；`-`／空值／非正數一律 None。"""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def mis_price(s):
    """現價優先序：z 成交價 → pz 上一筆成交價 → 最佳買賣中點 → 高低中點。無則 None。"""
    for k in ("z", "pz"):
        v = mis_num(s.get(k))
        if v:
            return v
    bv = mis_num((s.get("b") or "").split("_")[0])
    av = mis_num((s.get("a") or "").split("_")[0])
    if bv and av:
        return round((bv + av) / 2, 4)
    if bv or av:
        return bv or av
    h, l = mis_num(s.get("h")), mis_num(s.get("l"))
    if h and l:
        return round((h + l) / 2, 4)
    return None


def mis_batch(ex_chs, warn=None):
    """抓一批（pipe 串接）即時報價，回傳 msgArray；失敗回 []（warn 可傳 print 之類的輸出函式）。"""
    params = {"ex_ch": "|".join(ex_chs), "json": "1", "delay": "0",
              "_": str(int(time.time() * 1000))}
    try:
        r = requests.get(MIS_URL, params=params,
                         headers={"User-Agent": "Mozilla/5.0",
                                  "Referer": "https://mis.twse.com.tw/stock/index.jsp"},
                         timeout=30)
        b = r.json()
    except Exception as e:
        if warn:
            warn(f"  [warn] MIS batch 失敗: {e}")
        return []
    if b.get("rtcode") != "0000":
        if warn:
            warn(f"  [warn] MIS rtcode={b.get('rtcode')} {b.get('rtmessage')}")
        return []
    return b.get("msgArray", []) or []


def fetch_intraday_rows(symbols, today=None, warn=None):
    """抓 symbols 的即時報價，回傳 (rows, stats)。

    rows 直接餵給 `UPSERT_SQL`（execute_values），欄位＝
    (symbol, ts, open, high, low, close, volume, adj_factor)；volume 已由張換算成股。
    stats = {"missing": 無成交價跳過, "stale": 交易日防呆跳過, "today": 採用的台北日期}。

    交易日防呆：MIS `d` = 該檔最近交易日(YYYYMMDD)。非交易日（週末/國定假日）或開盤前，
    d 會停在上一交易日 → 跳過。**非交易日呼叫此函式必得 rows=[]，呼叫端據此不要寫任何資料。**
    """
    syms = set(symbols)
    today = today or today_tpe()
    today_str = today.strftime("%Y%m%d")
    chans = [to_channel(s) for s in sorted(syms)]
    rows, missing, stale = [], 0, 0
    for i in range(0, len(chans), BATCH):
        for s in mis_batch(chans[i:i + BATCH], warn=warn):
            code = (s.get("c") or "").strip()
            sym = code + (".TWO" if s.get("ex") == "otc" else ".TW")
            if sym not in syms:
                continue
            if (s.get("d") or "").strip() != today_str:
                stale += 1
                continue
            close = mis_price(s)
            if close is None:
                missing += 1
                continue
            o, h, l = mis_num(s.get("o")), mis_num(s.get("h")), mis_num(s.get("l"))
            vol_lots = mis_num(s.get("v"))                    # MIS 量單位＝張
            vol = int(vol_lots * 1000) if vol_lots else None  # → 股，對齊歷史
            rows.append((sym, today, o, h or close, l or close, close, vol, 1.0))
        time.sleep(PAUSE)
    return rows, {"missing": missing, "stale": stale, "today": today}
