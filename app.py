import streamlit as st
import pandas as pd
import numpy as np
import requests
import plotly.graph_objects as go
from datetime import datetime
import time
from enum import Enum
import concurrent.futures

# ============================================================
# পেজ কনফিগারেশন ও কাস্টম CSS
# ============================================================
st.set_page_config(page_title="🚀 Crypto Futures Signal Bot Pro (KuCoin)", layout="wide")

st.markdown("""
<style>
    .stApp { background: linear-gradient(135deg, #0b0e14 0%, #141b29 100%); }
    .css-1d391kg, .css-1lcbmhc { background: rgba(20, 27, 41, 0.9) !important; backdrop-filter: blur(10px); border-right: 1px solid #2a3a5e; }
    .stButton > button { background: linear-gradient(90deg, #00d4ff, #7b2ffc) !important; color: white !important; border-radius: 30px !important; border: none !important; padding: 0.6rem 2rem !important; font-weight: bold !important; box-shadow: 0 4px 15px rgba(0, 212, 255, 0.3) !important; transition: 0.3s !important; }
    .stButton > button:hover { transform: scale(1.05); box-shadow: 0 6px 25px rgba(0, 212, 255, 0.5) !important; }
    .signal-card { background: rgba(20, 30, 50, 0.8); backdrop-filter: blur(5px); border-radius: 16px; padding: 20px; border-left: 6px solid #00d4ff; box-shadow: 0 8px 32px rgba(0,0,0,0.5); margin-bottom: 10px; transition: 0.3s; border: 1px solid #2a3a5e; }
    .signal-card:hover { transform: translateY(-5px); border-color: #7b2ffc; }
    .buy-badge { background: linear-gradient(90deg, #00c853, #00e676); color: #000; font-weight: 900; padding: 4px 14px; border-radius: 30px; display: inline-block; font-size: 0.9rem; box-shadow: 0 0 20px rgba(0, 200, 80, 0.4); }
    .sell-badge { background: linear-gradient(90deg, #d50000, #ff1744); color: #fff; font-weight: 900; padding: 4px 14px; border-radius: 30px; display: inline-block; font-size: 0.9rem; box-shadow: 0 0 20px rgba(255, 20, 20, 0.4); }
    .hold-badge { background: linear-gradient(90deg, #ff9100, #ffab00); color: #000; font-weight: 900; padding: 4px 14px; border-radius: 30px; display: inline-block; font-size: 0.9rem; box-shadow: 0 0 20px rgba(255, 170, 0, 0.3); }
    .price-box { background: #1a2744; border-radius: 8px; padding: 8px 12px; margin: 4px 0; border-left: 3px solid #00d4ff; font-family: 'Courier New', monospace; }
    .full-price { font-family: 'Courier New', monospace; font-weight: bold; color: #ffffff; }
    .zone-buy { background: #00c85320; border-left: 4px solid #00c853; padding: 8px 12px; border-radius: 4px; }
    .zone-sell { background: #d5000020; border-left: 4px solid #d50000; padding: 8px 12px; border-radius: 4px; }
    .zone-neutral { background: #ffaa0020; border-left: 4px solid #ffaa00; padding: 8px 12px; border-radius: 4px; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# হেলপার: প্রাইস ফরম্যাট
# ============================================================
def format_price(price):
    if price is None or price == 0:
        return "N/A"
    return f"{price:.10f}".rstrip('0').rstrip('.')

# ============================================================
# ১. মার্কেট রেজিম ডিটেক্টর
# ============================================================
class MarketRegime(Enum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"

class MarketRegimeDetector:
    def __init__(self, adx_threshold=25, sma_period=20):
        self.adx_threshold = adx_threshold
        self.sma_period = sma_period

    def detect(self, df):
        try:
            adx = self._calculate_adx(df)
            sma = df['close'].rolling(self.sma_period).mean()
            sma_slope = sma.iloc[-1] - sma.iloc[-2] if len(sma) >= 2 else 0
            if adx > self.adx_threshold:
                return MarketRegime.BULL if sma_slope > 0 else MarketRegime.BEAR
            else:
                return MarketRegime.SIDEWAYS
        except:
            return MarketRegime.SIDEWAYS

    def _calculate_adx(self, df, period=14):
        try:
            high, low, close = df['high'], df['low'], df['close']
            tr1 = high - low
            tr2 = abs(high - close.shift())
            tr3 = abs(low - close.shift())
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(period).mean().iloc[-1]
            up_move = high.diff()
            down_move = -low.diff()
            plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
            minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
            plus_di = 100 * pd.Series(plus_dm).rolling(period).mean() / atr if atr != 0 else 0
            minus_di = 100 * pd.Series(minus_dm).rolling(period).mean() / atr if atr != 0 else 0
            dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di) if (plus_di + minus_di) != 0 else 0
            return dx.rolling(period).mean().iloc[-1]
        except:
            return 20

# ============================================================
# ২. ইন্ডিকেটর ফাংশন (৫টি)
# ============================================================
def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    if rs.iloc[-1] == 0 or pd.isna(rs.iloc[-1]):
        return 50
    return 100 - (100 / (1 + rs.iloc[-1]))

def calculate_macd(df, fast=12, slow=26, signal=9):
    ema_fast = df['close'].ewm(span=fast, adjust=False).mean()
    ema_slow = df['close'].ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line.iloc[-1], signal_line.iloc[-1]

def calculate_bb(df, period=20):
    sma = df['close'].rolling(period).mean()
    std = df['close'].rolling(period).std()
    return sma.iloc[-1] + 2*std.iloc[-1], sma.iloc[-1] - 2*std.iloc[-1]

def calculate_volume_profile_poc(df, num_levels=20):
    try:
        price_min = df['low'].min()
        price_max = df['high'].max()
        if price_max == price_min:
            return df['close'].iloc[-1]
        step = (price_max - price_min) / num_levels
        levels = np.arange(price_min, price_max + step, step)
        volumes = []
        for i in range(len(levels)-1):
            mask = (df['close'] >= levels[i]) & (df['close'] < levels[i+1])
            volumes.append(df.loc[mask, 'volume'].sum())
        if not volumes or max(volumes) == 0:
            return df['close'].iloc[-1]
        poc_idx = np.argmax(volumes)
        return (levels[poc_idx] + levels[poc_idx+1]) / 2
    except:
        return df['close'].iloc[-1]

# ============================================================
# ৩. সিম্পল মেজরিটি ভোটিং সিস্টেম
# ============================================================
def voting_signal(df):
    vote_items = []
    votes = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
    
    try:
        rsi = calculate_rsi(df)
        if rsi < 30: v = 'BUY'
        elif rsi > 70: v = 'SELL'
        else: v = 'HOLD'
        vote_items.append({'name': 'RSI', 'vote': v, 'value': f"{rsi:.1f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'RSI', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    try:
        macd_line, signal_line = calculate_macd(df)
        v = 'BUY' if macd_line > signal_line else 'SELL'
        vote_items.append({'name': 'MACD', 'vote': v, 'value': f"{macd_line:.4f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'MACD', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    try:
        ema_short = df['close'].ewm(span=20).mean().iloc[-1]
        ema_long = df['close'].ewm(span=50).mean().iloc[-1]
        v = 'BUY' if ema_short > ema_long else 'SELL'
        vote_items.append({'name': 'EMA(20/50)', 'vote': v, 'value': f"{ema_short:.2f}/{ema_long:.2f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'EMA(20/50)', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    try:
        upper, lower = calculate_bb(df)
        last_price = df['close'].iloc[-1]
        if last_price <= lower: v = 'BUY'
        elif last_price >= upper: v = 'SELL'
        else: v = 'HOLD'
        vote_items.append({'name': 'Bollinger', 'vote': v, 'value': f"U:{upper:.2f} L:{lower:.2f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'Bollinger', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    try:
        poc = calculate_volume_profile_poc(df)
        last_price = df['close'].iloc[-1]
        if last_price > poc: v = 'BUY'
        elif last_price < poc: v = 'SELL'
        else: v = 'HOLD'
        vote_items.append({'name': 'Vol Profile', 'vote': v, 'value': f"POC: {poc:.4f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'Vol Profile', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    if votes['BUY'] >= 3: final_signal = 'BUY'
    elif votes['SELL'] >= 3: final_signal = 'SELL'
    else: final_signal = 'HOLD'

    return final_signal, votes, vote_items

# ============================================================
# ৪. ট্রেন্ড লাইন ও সাপোর্ট/রেসিস্টেন্স
# ============================================================
def calculate_trendline_points(df, order=5, lookback=50):
    data = df.tail(lookback).copy()
    data.reset_index(drop=True, inplace=True)
    highs, lows = data['high'].values, data['low'].values
    
    pivot_lows = [i for i in range(order, len(data) - order) if lows[i] == min(lows[i-order:i+order+1])]
    pivot_highs = [i for i in range(order, len(data) - order) if highs[i] == max(highs[i-order:i+order+1])]
    
    uptrend_x, uptrend_y = None, None
    if len(pivot_lows) >= 2:
        x1, y1 = pivot_lows[-2], lows[pivot_lows[-2]]
        x2, y2 = pivot_lows[-1], lows[pivot_lows[-1]]
        if x2 > x1 and y2 > y1:
            slope = (y2 - y1) / (x2 - x1)
            end_x = len(data) - 1
            uptrend_x = [data.loc[x1, 'timestamp'], data.loc[end_x, 'timestamp']]
            uptrend_y = [y1, y1 + slope * (end_x - x1)]

    downtrend_x, downtrend_y = None, None
    if len(pivot_highs) >= 2:
        x1, y1 = pivot_highs[-2], highs[pivot_highs[-2]]
        x2, y2 = pivot_highs[-1], highs[pivot_highs[-1]]
        if x2 > x1 and y2 < y1:
            slope = (y2 - y1) / (x2 - x1)
            end_x = len(data) - 1
            downtrend_x = [data.loc[x1, 'timestamp'], data.loc[end_x, 'timestamp']]
            downtrend_y = [y1, y1 + slope * (end_x - x1)]

    return uptrend_x, uptrend_y, downtrend_x, downtrend_y

def calculate_support_resistance(df, lookback=30, num_levels=3):
    try:
        data = df.tail(lookback)
        highs, lows = data['high'].values, data['low'].values
        pivot_highs = [highs[i] for i in range(2, len(data)-2) if highs[i] == max(highs[i-2:i+3])]
        pivot_lows = [lows[i] for i in range(2, len(data)-2) if lows[i] == min(lows[i-2:i+3])]
        
        def cluster(values, tolerance=0.001):
            if not values: return []
            values = sorted(values)
            clusters, current = [], [values[0]]
            for v in values[1:]:
                if abs(v - current[-1]) / current[-1] < tolerance: current.append(v)
                else: clusters.append(np.mean(current)); current = [v]
            clusters.append(np.mean(current))
            return clusters
            
        resistance = cluster(pivot_highs)[-num_levels:] if pivot_highs else [highs.max()]
        support = cluster(pivot_lows)[:num_levels] if pivot_lows else [lows.min()]
        return support[:num_levels], resistance[:num_levels]
    except:
        return [df['low'].quantile(0.2)], [df['high'].quantile(0.8)]

def create_candlestick_chart(df, support, resistance, uptrend_line, downtrend_line, title="Price Chart"):
    fig = go.Figure(data=[go.Candlestick(
        x=df['timestamp'], open=df['open'], high=df['high'],
        low=df['low'], close=df['close'], name="Candles"
    )])
    for level in support:
        fig.add_hline(y=level, line_dash="dash", line_color="#ff6b6b", opacity=0.8, annotation_text=f"S {level:.6f}")
    for level in resistance:
        fig.add_hline(y=level, line_dash="dash", line_color="#51cf66", opacity=0.8, annotation_text=f"R {level:.6f}")
    if uptrend_line:
        fig.add_trace(go.Scatter(x=uptrend_line[0], y=uptrend_line[1], mode="lines", name="আপট্রেন্ড", line=dict(color="#00d4ff", width=3, dash="dot")))
    if downtrend_line:
        fig.add_trace(go.Scatter(x=downtrend_line[0], y=downtrend_line[1], mode="lines", name="ডাউনট্রেন্ড", line=dict(color="#ff922b", width=3, dash="dot")))
    fig.update_layout(template="plotly_dark", height=550, xaxis_rangeslider_visible=False, title=title)
    return fig

def get_price_trigger_zone(price, support, resistance):
    nearest_support = max([s for s in support if s < price], default=None)
    nearest_resistance = min([r for r in resistance if r > price], default=None)
    zone, details = "NEUTRAL", "দাম সাপোর্ট ও রেজিস্টেন্স থেকে দূরে।"
    if nearest_support:
        diff_pct = abs((price - nearest_support) / price) * 100
        if diff_pct < 1.0: return "BUY ZONE", f"সাপোর্ট ({format_price(nearest_support)}) এর খুব কাছাকাছি।"
    if nearest_resistance:
        diff_pct = abs((nearest_resistance - price) / price) * 100
        if diff_pct < 1.0: return "SELL ZONE", f"রেজিস্টেন্স ({format_price(nearest_resistance)}) এর খুব কাছাকাছি।"
    return zone, details

def calculate_atr(df, period=14):
    try:
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(period).mean().iloc[-1]
    except:
        return (df['high'].iloc[-1] - df['low'].iloc[-1]) * 0.5

# ============================================================
# ৫. কুয়োকয়েন (KuCoin Futures) ডেটা ফেচ ও পেয়ার লোড
# ============================================================
@st.cache_data(ttl=300)
def fetch_klines(symbol, interval="1h", limit=100):
    try:
        # KUCOIN ফরম্যাট: যেমন BTCUSDT -> XBTUSDTM বা BTCUSDTM
        clean_sym = symbol.replace("USDT", "").replace("USDTM", "")
        if clean_sym == "BTC": clean_sym = "XBT"
        kucoin_symbol = f"{clean_sym}USDTM"
        
        granularity_map = {"1h": "1hour", "2h": "2hour", "4h": "4hour", "1d": "1day"}
        granularity = granularity_map.get(interval.lower(), "1hour")
        
        url = f"https://api-futures.kucoin.com/api/v1/kline/query?symbol={kucoin_symbol}&granularity={granularity}&limit={limit}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        res = resp.json()
        
        if res.get('code') != '200000' or not res.get('data'):
            return None
            
        data = res['data']
        # কুয়োকয়েন লেটেস্ট আগে দেয়, তাই রিভার্স করতে হবে
        data.reverse()
        
        df = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'].astype(float), unit='ms')
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        return None

@st.cache_data(ttl=3600)
def get_all_usdt_pairs(min_volume_usdt=500000):
    try:
        url = "https://api-futures.kucoin.com/api/v1/ticker/all-tickers"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        res = resp.json()
        
        if res.get('code') != '200000':
            return []
            
        tickers = res.get('data', {}).get('ticker', [])
        usdt_pairs = []
        for item in tickers:
            sym = item.get('symbol', '')
            if sym.endswith('USDTM'):
                base_sym = sym.replace('USDTM', '')
                if base_sym == 'XBT': base_sym = 'BTC'
                symbol = f"{base_sym}USDT"
                
                try:
                    price = float(item.get('price', 0))
                    turnover = float(item.get('turnoverOf24h', 0)) # USDT ভলিউম
                    if turnover < min_volume_usdt: continue
                    usdt_pairs.append({'symbol': symbol, 'volume': turnover, 'price': price})
                except:
                    continue
        usdt_pairs.sort(key=lambda x: x['volume'], reverse=True)
        return usdt_pairs
    except Exception as e:
        return []

# ============================================================
# ৬. সিগন্যাল জেনারেটর
# ============================================================
def generate_signal(df, current_tf="1h", symbol=None):
    try:
        final_signal, votes, vote_items = voting_signal(df)
        last_price = df['close'].iloc[-1]
        current_atr = calculate_atr(df)
        
        if final_signal == "SELL":
            stop_loss = last_price + (current_atr * 1.8)
            take_profit = last_price - (current_atr * 3.5)
        else:
            stop_loss = last_price - (current_atr * 1.8)
            take_profit = last_price + (current_atr * 3.5)
            
        tp_pct = abs((take_profit - last_price) / last_price) * 100
        if tp_pct < 3.0:
            take_profit = last_price * (1 - 0.03 if final_signal == "SELL" else 1 + 0.03)
            
        detector = MarketRegimeDetector()
        regime = detector.detect(df)
        
        return {
            "signal": final_signal, "regime": regime.value, "strategy": "majority_voting",
            "entry_price": last_price, "stop_loss": stop_loss, "take_profit": take_profit,
            "trailing_stop_price": take_profit, "position_size": 1.0,
            "sl_percent": abs((last_price - stop_loss) / last_price) * 100,
            "tp_percent": abs((take_profit - last_price) / last_price) * 100,
            "reason": "কুয়োকয়েন ফিউচার্স লাইভ সিগন্যাল", "rsi": calculate_rsi(df),
            "votes": votes, "vote_items": vote_items
        }
    except Exception as e:
        return {"signal": "ERROR", "regime": "error", "reason": str(e), "votes": {'BUY':0,'SELL':0,'HOLD':5}, "vote_items": []}

# ============================================================
# ৭. স্ক্যানার
# ============================================================
def scan_market(pairs, interval, limit_candles=100):
    results = []
    progress = st.progress(0)
    status = st.empty()
    total = len(pairs)
    
    def process(pair):
        df = fetch_klines(pair['symbol'], interval=interval, limit=limit_candles)
        if df is not None and len(df) > 30:
            sig = generate_signal(df, current_tf=interval, symbol=pair['symbol'])
            return {
                'symbol': pair['symbol'], 'price': pair['price'], 'signal': sig['signal'],
                'entry_price': sig['entry_price'], 'rsi': sig['rsi'],
                'votes_buy': sig['votes']['BUY'], 'votes_sell': sig['votes']['SELL']
            }
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(process, p) for p in pairs]
        for i, f in enumerate(concurrent.futures.as_completed(futures)):
            res = f.result()
            if res: results.append(res)
            progress.progress((i + 1) / total)
            status.text(f"স্ক্যানিং: {i+1}/{total}")
    status.text("স্ক্যান সম্পূর্ণ!")
    return pd.DataFrame(results)

# ============================================================
# ৮. মেইন UI
# ============================================================
st.title("🤖 ক্রিপ্টো ফিউচার সিগন্যাল বট (KuCoin API)")
st.markdown("### 📊 ফর্মুলা: BUY≥৩ ➜ BUY | SELL≥৩ ➜ SELL | অন্যথায় HOLD")

mode = st.sidebar.radio("মোড নির্বাচন করুন", ["🔍 সিঙ্গেল কয়েন অ্যানালাইসিস", "📡 মার্কেট স্ক্যানার"])

if mode == "🔍 সিঙ্গেল কয়েন অ্যানালাইসিস":
    symbol = st.sidebar.text_input("সিম্বল", value="BTCUSDT")
    timeframe = st.sidebar.selectbox("টাইমফ্রেম", ["1h", "2h", "4h"])
    
    if st.sidebar.button("🚀 সিগন্যাল জেনারেট করো", type="primary"):
        with st.spinner("কুয়োকয়েন থেকে ডেটা আনা হচ্ছে..."):
            df = fetch_klines(symbol, interval=timeframe)
            if df is not None and not df.empty:
                support, resistance = calculate_support_resistance(df)
                uptrend_x, uptrend_y, downtrend_x, downtrend_y = calculate_trendline_points(df)
                sig = generate_signal(df, current_tf=timeframe, symbol=symbol)
                
                col1, col2 = st.columns([2, 1])
                with col1:
                    fig = create_candlestick_chart(df, support, resistance, 
                                                   (uptrend_x, uptrend_y) if uptrend_x else None, 
                                                   (downtrend_x, downtrend_y) if downtrend_x else None, 
                                                   f"{symbol} - {timeframe}")
                    st.plotly_chart(fig, use_container_width=True)
                with col2:
                    st.markdown(f"""
                    <div class="signal-card">
                        <h3>{symbol}</h3>
                        <p>মূল্য: <b class="full-price">${format_price(sig['entry_price'])}</b></p>
                        <p>সিগন্যাল: <span class="{'buy-badge' if sig['signal']=='BUY' else 'sell-badge' if sig['signal']=='SELL' else 'hold-badge'}">{sig['signal']}</span></p>
                        <p>RSI: <b>{sig['rsi']:.1f}</b></p>
                        <hr style="border-color:#2a3a5e;">
                        <div class="price-box">🚀 এন্ট্রি: <b class="full-price">${format_price(sig['entry_price'])}</b></div>
                        <div class="price-box" style="border-left-color: #ff4444;">🛑 স্টপ-লস: <b class="full-price">${format_price(sig['stop_loss'])}</b></div>
                        <div class="price-box" style="border-left-color: #00c853;">🎯 টার্গেট: <b class="full-price">${format_price(sig['take_profit'])}</b></div>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.error("কুয়োকয়েন থেকে ডেটা পাওয়া যায়নি। সিম্বল সঠিক আছে কি না চেক করুন (যেমন: BTCUSDT, ETHUSDT)।")

else:
    st.markdown("### 📡 কুয়োকয়েন মার্কেট স্ক্যানার")
    min_vol = st.number_input("সর্বনিম্ন ভলিউম (USDT)", value=1000000, step=500000)
    if st.button("🚀 স্ক্যান শুরু করো", type="primary"):
        pairs = get_all_usdt_pairs(min_volume_usdt=min_vol)
        if pairs:
            df_res = scan_market(pairs, interval="1h")
            if not df_res.empty:
                st.dataframe(df_res, use_container_width=True)
            else:
                st.warning("কোনো পেয়ারে সিগন্যাল পাওয়া যায়নি।")
        else:
                    st.warning("কুয়োকয়েন থেকে পেয়ার লিস্ট লোড করা যায়নি।")
