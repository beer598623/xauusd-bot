import requests, datetime, os
import pandas as pd

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = os.environ.get("CHAT_ID", "")

BALANCE  = 100
RISK_PCT = 20.0
TP1_RR   = 1.5
TP2_RR   = 2.5
TP3_RR   = 4.0
SYMBOL   = "GC=F"
HEADERS  = {"User-Agent": "Mozilla/5.0"}

def in_session():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    h   = now.hour
    return 14 <= h < 22, now.strftime("%H:%M"), now

def fetch_yahoo(interval, period):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        + SYMBOL
        + "?interval=" + interval
        + "&range=" + period
    )
    r = requests.get(url, headers=HEADERS, timeout=15)
    d = r.json()["chart"]["result"][0]
    q = d["indicators"]["quote"][0]
    df = pd.DataFrame({
        "open" : q["open"],
        "high" : q["high"],
        "low"  : q["low"],
        "close": q["close"]
    }).dropna()
    return df

def calc_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def calc_atr(df, p=14):
    h, l, c = df["high"], df["low"], df["close"]
    tr = pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(p).mean().iloc[-1]

def calc_rsi(series, p=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(p).mean()
    loss  = (-delta.clip(upper=0)).rolling(p).mean()
    rs    = gain / loss
    return (100 - 100 / (1 + rs)).iloc[-1]

def calc_macd(series):
    fast   = calc_ema(series, 12)
    slow   = calc_ema(series, 26)
    macd   = fast - slow
    signal = calc_ema(macd, 9)
    return macd.iloc[-1] > signal.iloc[-1]

def get_swings(df, n=5):
    hi, lo = df["high"].values, df["low"].values
    sh = sl = None
    for i in range(n, len(hi) - n):
        if all(hi[i] >= hi[i-n:i]) and all(hi[i] >= hi[i+1:i+n+1]):
            sh = hi[i]
        if all(lo[i] <= lo[i-n:i]) and all(lo[i] <= lo[i+1:i+n+1]):
            sl = lo[i]
    return sh, sl

def get_daily_bias(df_daily):
    cl = df_daily["close"]
    if len(cl) < 10:
        return "NEUTRAL"
    ema20 = calc_ema(cl, 20).iloc[-1]
    ema50 = calc_ema(cl, 50).iloc[-1]
    if ema20 > ema50:
        return "BULL"
    elif ema20 < ema50:
        return "BEAR"
    return "NEUTRAL"

def get_h4_level(df_h4):
    if len(df_h4) < 20:
        return None, None
    cl, hi, lo = df_h4["close"], df_h4["high"], df_h4["low"]
    atr  = calc_atr(df_h4)
    fmin = atr * 0.2
    bull_fvg = lo.iloc[-1] > hi.iloc[-3] and (lo.iloc[-1] - hi.iloc[-3]) > fmin
    bear_fvg = hi.iloc[-1] < lo.iloc[-3] and (lo.iloc[-3] - hi.iloc[-1]) > fmin
    sh, sl   = get_swings(df_h4)
    bull_sweep = sl is not None and lo.iloc[-2] < sl and cl.iloc[-2] > sl
    bear_sweep = sh is not None and hi.iloc[-2] > sh and cl.iloc[-2] < sh
    h4_bull = bull_fvg or bull_sweep
    h4_bear = bear_fvg or bear_sweep
    return h4_bull, h4_bear

def analyze_h1(df_h1, bias):
    if len(df_h1) < 50:
        return None
    cl, hi, lo = df_h1["close"], df_h1["high"], df_h1["low"]
    cp  = cl.iloc[-1]
    atr = calc_atr(df_h1)
    e20 = calc_ema(cl, 20).iloc[-1]
    e50 = calc_ema(cl, 50).iloc[-1]
    sh, sl   = get_swings(df_h1)
    fmin     = atr * 0.2
    bull_bias  = e20 > e50
    bear_bias  = e20 < e50
    bull_sweep = sl is not None and lo.iloc[-2] < sl and cl.iloc[-2] > sl
    bear_sweep = sh is not None and hi.iloc[-2] > sh and cl.iloc[-2] < sh
    bull_fvg   = lo.iloc[-1] > hi.iloc[-3] and (lo.iloc[-1] - hi.iloc[-3]) > fmin
    bear_fvg   = hi.iloc[-1] < lo.iloc[-3] and (lo.iloc[-3] - hi.iloc[-1]) > fmin
    bull_mss   = sh is not None and cl.iloc[-1] > sh and cl.iloc[-2] <= sh
    bear_mss   = sl is not None and cl.iloc[-1] < sl and cl.iloc[-2] >= sl
    macd_bull  = calc_macd(cl)
    rsi_val    = calc_rsi(cl)
    bull_rsi   = 50 < rsi_val < 70
    bear_rsi   = 30 < rsi_val < 50
    buy  = (bias == "BULL" and bull_bias and
            (bull_sweep or bull_fvg) and macd_bull and bull_rsi)
    sell = (bias == "BEAR" and bear_bias and
            (bear_sweep or bear_fvg) and not macd_bull and bear_rsi)
    score = 0
    if buy or sell:
        if bull_bias or bear_bias:               score += 1
        if bull_sweep or bear_sweep:             score += 1
        if bull_fvg or bear_fvg:                 score += 1
        if bull_mss or bear_mss:                 score += 1
        if macd_bull == buy:                     score += 1
        if (bull_rsi and buy) or (bear_rsi and sell): score += 1
    return {
        "dir"       : "BUY" if buy else "SELL" if sell else "WAIT",
        "price"     : cp, "atr": atr,
        "e20"       : e20, "e50": e50,
        "rsi"       : rsi_val, "macd_bull": macd_bull,
        "bull_bias" : bull_bias, "bear_bias": bear_bias,
        "bull_sweep": bull_sweep, "bear_sweep": bear_sweep,
        "bull_fvg"  : bull_fvg, "bear_fvg": bear_fvg,
        "bull_mss"  : bull_mss, "bear_mss": bear_mss,
        "score"     : score, "sh": sh, "sl_swing": sl
    }

def get_m15_fvg(df_m15, direction):
    if len(df_m15) < 20:
        return None, None
    hi, lo = df_m15["high"], df_m15["low"]
    atr    = calc_atr(df_m15)
    fmin   = atr * 0.1
    fvg_lo = fvg_hi = None
    for i in range(3, len(df_m15) - 1):
        if direction == "BUY":
            gap = lo.iloc[i] - hi.iloc[i-2]
            if gap > fmin:
                fvg_lo = hi.iloc[i-2]
                fvg_hi = lo.iloc[i]
        else:
            gap = lo.iloc[i-2] - hi.iloc[i]
            if gap > fmin:
                fvg_lo = hi.iloc[i]
                fvg_hi = lo.iloc[i-2]
    return fvg_lo, fvg_hi

def calc_levels(a, fvg_lo, fvg_hi):
    risk = BALANCE * RISK_PCT / 100
    cp, atr = a["price"], a["atr"]
    entry = fvg_lo if fvg_lo else cp
    if a["dir"] == "BUY":
        sl   = (a["sl_swing"] - atr * 0.2) if a["sl_swing"] else entry - atr
        diff = entry - sl
        tp1, tp2, tp3 = entry+diff*TP1_RR, entry+diff*TP2_RR, entry+diff*TP3_RR
    else:
        sl   = (a["sh"] + atr * 0.2) if a["sh"] else entry + atr
        diff = sl - entry
        tp1, tp2, tp3 = entry-diff*TP1_RR, entry-diff*TP2_RR, entry-diff*TP3_RR
    sl_pts = max(1, round(diff * 10))
    lot    = max(0.01, risk / sl_pts)
    lot1   = round(lot * 0.5, 2)
    lot2   = round(lot * 0.3, 2)
    lot3   = round(lot * 0.2, 2)
    return {
        "entry": entry, "sl": sl,
        "tp1": tp1, "tp2": tp2, "tp3": tp3,
        "sl_pts": sl_pts, "lot": lot,
        "lot1": lot1, "lot2": lot2, "lot3": lot3,
        "risk": risk,
        "fvg_lo": fvg_lo, "fvg_hi": fvg_hi
    }

def send(msg):
    requests.post(
        "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"},
        timeout=10
    )

def main():
    in_sess, time_str, now_dt = in_session()
    if not in_sess:
        print("[" + time_str + "] นอก Session - ข้าม")
        return

    print("[" + time_str + "] วิเคราะห์ XAUUSD SMC Multi-TF...")

    df_daily = fetch_yahoo("1d", "3mo")
    df_h4    = fetch_yahoo("4h", "1mo")
    df_h1    = fetch_yahoo("1h", "5d")
    df_m15   = fetch_yahoo("15m", "5d")

    daily_bias = get_daily_bias(df_daily)
    if daily_bias == "NEUTRAL":
        print("Daily Bias: NEUTRAL - ข้าม")
        return

    h4_bull, h4_bear = get_h4_level(df_h4)
    if daily_bias == "BULL" and not h4_bull:
        print("H4 ไม่ยืนยัน BULL - ข้าม")
        return
    if daily_bias == "BEAR" and not h4_bear:
        print("H4 ไม่ยืนยัน BEAR - ข้าม")
        return

    a = analyze_h1(df_h1, daily_bias)
    if not a or a["dir"] == "WAIT":
        print("H1 Setup: WAIT - ข้าม")
        return

    if a["score"] < 4:
        print("Score " + str(a["score"]) + "/6 ต่ำเกิน - ข้าม")
        return

    fvg_lo, fvg_hi = get_m15_fvg(df_m15, a["dir"])
    lv = calc_levels(a, fvg_lo, fvg_hi)

    now_str = now_dt.strftime("%d/%m/%Y %H:%M")

    fvg_zone = "N/A"
    if fvg_lo and fvg_hi:
        fvg_zone = str(round(fvg_lo, 2)) + " - " + str(round(fvg_hi, 2))

    msg = (
        "XAUUSD SMC Multi-TF\n"
        + a["dir"] + " SETUP | Score: " + str(a["score"]) + "/6\n"
        + now_str + " GMT+7\n\n"
        + "Daily Bias : " + daily_bias + "\n"
        + "H4 Confirm : OK\n"
        + "H1 Price   : " + str(round(a["price"], 2)) + " USD\n"
        + "H1 EMA     : " + ("BULL" if a["bull_bias"] else "BEAR") + "\n"
        + "H1 RSI     : " + str(round(a["rsi"], 1)) + "\n"
        + "H1 MACD    : " + ("BULL" if a["macd_bull"] else "BEAR") + "\n\n"
        + "H1 Checklist:\n"
        + ("OK " if a["bull_sweep"] or a["bear_sweep"] else "NO ") + "Liquidity Sweep\n"
        + ("OK " if a["bull_fvg"]   or a["bear_fvg"]   else "NO ") + "Fair Value Gap\n"
        + ("OK " if a["bull_mss"]   or a["bear_mss"]   else "NO ") + "MSS\n\n"
        + "M15 FVG Entry Zone:\n"
        + fvg_zone + " USD\n"
        + "รอราคา Pullback มาแตะ Zone\n\n"
        + "ENTRY PLAN\n"
        + "Entry : " + str(round(lv["entry"], 2)) + "\n"
        + "SL    : " + str(round(lv["sl"], 2)) + " (-" + str(lv["sl_pts"]) + " pts)\n\n"
        + "TP1 (1:" + str(TP1_RR) + ") : " + str(round(lv["tp1"], 2)) + " | Lot: " + str(lv["lot1"]) + "\n"
        + "TP2 (1:" + str(TP2_RR) + ") : " + str(round(lv["tp2"], 2)) + " | Lot: " + str(lv["lot2"]) + "\n"
        + "TP3 (1:" + str(TP3_RR) + ") : " + str(round(lv["tp3"], 2)) + " | Lot: " + str(lv["lot3"]) + "\n\n"
        + "SL ทุก Order: " + str(round(lv["sl"], 2)) + "\n"
        + "Risk: $" + str(round(lv["risk"], 2)) + " (" + str(RISK_PCT) + "%)"
    )

    send(msg)
    print("ส่ง " + a["dir"] + " Signal แล้ว! Score: " + str(a["score"]) + "/6")

if __name__ == "__main__":
    main()
