import requests, datetime, os
import pandas as pd

BOT_TOKEN = os.environ['BOT_TOKEN']
CHAT_ID   = os.environ['CHAT_ID']

BALANCE  = 100
RISK_PCT = 20.0
TP1_RR   = 1.5
TP2_RR   = 2.5
TP3_RR   = 4.0
SYMBOL   = 'GC=F'
HEADERS  = {'User-Agent': 'Mozilla/5.0'}

def in_window():
    now = datetime.datetime.utcnow() + datetime.timedelta(hours=7)
    h   = now.hour
    if h == 15: return True, '🔵 London SB 15:00'
    if h == 22: return True, '🟢 NY AM SB 22:00'
    return False, ''

def fetch_candles():
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}?interval=1m&range=1d'
    r   = requests.get(url, headers=HEADERS, timeout=15)
    d   = r.json()['chart']['result'][0]
    q   = d['indicators']['quote'][0]
    return pd.DataFrame({'open':q['open'],'high':q['high'],'low':q['low'],'close':q['close']}).dropna()

def calc_atr(df, p=14):
    h,l,c = df['high'],df['low'],df['close']
    tr = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.rolling(p).mean().iloc[-1]

def get_swings(df, n=5):
    hi,lo = df['high'].values, df['low'].values
    sh = sl = None
    for i in range(n, len(hi)-n):
        if all(hi[i]>=hi[i-n:i]) and all(hi[i]>=hi[i+1:i+n+1]): sh=hi[i]
        if all(lo[i]<=lo[i-n:i]) and all(lo[i]<=lo[i+1:i+n+1]): sl=lo[i]
    return sh, sl

def analyze(df):
    if len(df) < 30: return None
    cl,hi,lo = df['close'],df['high'],df['low']
    cp  = cl.iloc[-1]
    atr = calc_atr(df)
    e20 = cl.ewm(span=20,adjust=False).mean().iloc[-1]
    e50 = cl.ewm(span=50,adjust=False).mean().iloc[-1]
    sh,sl = get_swings(df)
    bull_bias  = e20 > e50
    bull_sweep = sl is not None and lo.iloc[-2]<sl and cl.iloc[-2]>sl
    bear_sweep = sh is not None and hi.iloc[-2]>sh and cl.iloc[-2]<sh
    fmin       = atr*0.2
    bull_fvg   = lo.iloc[-1]>hi.iloc[-3] and (lo.iloc[-1]-hi.iloc[-3])>fmin
    bear_fvg   = hi.iloc[-1]<lo.iloc[-3] and (lo.iloc[-3]-hi.iloc[-1])>fmin
    bull_mss   = sh is not None and cl.iloc[-1]>sh and cl.iloc[-2]<=sh
    bear_mss   = sl is not None and cl.iloc[-1]<sl and cl.iloc[-2]>=sl
    buy  = bull_bias  and bull_sweep and (bull_fvg or bull_mss)
    sell = not bull_bias and bear_sweep and (bear_fvg or bear_mss)
    return {
        'dir'        : 'BUY' if buy else 'SELL' if sell else 'WAIT',
        'price'      : cp, 'atr': atr,
        'bull_bias'  : bull_bias,
        'bull_sweep' : bull_sweep, 'bear_sweep': bear_sweep,
        'bull_fvg'   : bull_fvg,   'bear_fvg'  : bear_fvg,
        'bull_mss'   : bull_mss,   'bear_mss'  : bear_mss,
        'sh': sh, 'sl': sl
    }

def calc_levels(a):
    risk = BALANCE * RISK_PCT / 100
    cp, atr = a['price'], a['atr']
    if a['dir'] == 'BUY':
        sl   = (a['sl'] - atr*0.2) if a['sl'] else cp - atr
        diff = cp - sl
        tp1,tp2,tp3 = cp+diff*TP1_RR, cp+diff*TP2_RR, cp+diff*TP3_RR
    else:
        sl   = (a['sh'] + atr*0.2) if a['sh'] else cp + atr
        diff = sl - cp
        tp1,tp2,tp3 = cp-diff*TP1_RR, cp-diff*TP2_RR, cp-diff*TP3_RR
    pts = max(1, round(diff*10))
    lot = max(0.01, risk/pts)
    return {'sl':sl,'tp1':tp1,'tp2':tp2,'tp3':tp3,'pts':pts,'lot':lot,'risk':risk}

def send(msg):
    requests.post(
        f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage',
        data={'chat_id':CHAT_ID,'text':msg,'parse_mode':'Markdown'},
        timeout=10
    )

def main():
    in_win, win_name = in_window()
    if not in_win:
        now = (datetime.datetime.utcnow()+datetime.timedelta(hours=7)).strftime('%H:%M')
        print(f'[{now}] ไม่อยู่ใน Silver Bullet Window — ข้าม')
        return

    print(f'อยู่ใน {win_name} — กำลังวิเคราะห์...')
    df = fetch_candles()
    a  = analyze(df)

    if not a or a['dir'] == 'WAIT':
        print('Signal: WAIT — ไม่ส่ง')
        return

    lv  = calc_levels(a)
    fmt = lambda v: f'{v:,.2f}'
    e   = '🟢' if a['dir'] == 'BUY' else '🔴'
    now = (datetime.datetime.utcnow()+datetime.timedelta(hours=7)).strftime('%d/%m/%Y %H:%M')

    msg = f"""⚡ *XAUUSD Silver Bullet*
{e} *{a['dir']} SETUP*
🕐 {win_name} | {now} GMT+7

*💰 ราคา:* {fmt(a['price'])} USD
*Bias:* {'🟢 BULL' if a['bull_bias'] else '🔴 BEAR'}

*📋 SMC Checklist:*
{'✅' if a['bull_sweep'] or a['bear_sweep'] else '❌'} Liquidity Sweep
{'✅' if a['bull_fvg']   or a['bear_fvg']   else '❌'} Fair Value Gap
{'✅' if a['bull_mss']   or a['bear_mss']   else '❌'} MSS

*🎯 ENTRY PLAN*
📍 Entry : *{fmt(a['price'])}*
🛑 SL    : *{fmt(lv['sl'])}* (-{lv['pts']} pts)
🎯 TP1 (1:{TP1_RR}): *{fmt(lv['tp1'])}*
🎯 TP2 (1:{TP2_RR}): *{fmt(lv['tp2'])}*
🎯 TP3 (1:{TP3_RR}): *{fmt(lv['tp3'])}*

*💼 Lot:* {lv['lot']:.3f} oz
*Risk:* ${lv['risk']:.2f} ({RISK_PCT}%)
⚠️ วิเคราะห์ช่วยตัดสินใจเท่านั้น"""

    send(msg)
    print(f'✅ ส่ง {a["dir"]} Signal เข้า Telegram แล้ว!')

if __name__ == '__main__':
    main()
