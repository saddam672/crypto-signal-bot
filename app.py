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
st.set_page_config(page_title="🚀 Crypto Futures Signal Bot Pro", layout="wide")

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
    """
    ফর্মুলা: ৫টি ইন্ডিকেটর ভোট দেয়।
    BUY >= 3 হলে BUY
    SELL >= 3 হলে SELL
    নইলে HOLD
    """
    vote_items = []
    votes = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
    
    # ১. RSI
    try:
        rsi = calculate_rsi(df)
        if rsi < 30:
            v = 'BUY'
        elif rsi > 70:
            v = 'SELL'
        else:
            v = 'HOLD'
        vote_items.append({'name': 'RSI', 'vote': v, 'value': f"{rsi:.1f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'RSI', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    # ২. MACD
    try:
        macd_line, signal_line = calculate_macd(df)
        if macd_line > signal_line:
            v = 'BUY'
        else:
            v = 'SELL'
        vote_items.append({'name': 'MACD', 'vote': v, 'value': f"{macd_line:.4f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'MACD', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    # ৩. EMA ক্রস (২০/৫০)
    try:
        ema_short = df['close'].ewm(span=20).mean().iloc[-1]
        ema_long = df['close'].ewm(span=50).mean().iloc[-1]
        if ema_short > ema_long:
            v = 'BUY'
        else:
            v = 'SELL'
        vote_items.append({'name': 'EMA(20/50)', 'vote': v, 'value': f"{ema_short:.2f}/{ema_long:.2f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'EMA(20/50)', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    # ৪. Bollinger Bands
    try:
        upper, lower = calculate_bb(df)
        last_price = df['close'].iloc[-1]
        if last_price <= lower:
            v = 'BUY'
        elif last_price >= upper:
            v = 'SELL'
        else:
            v = 'HOLD'
        vote_items.append({'name': 'Bollinger', 'vote': v, 'value': f"U:{upper:.2f} L:{lower:.2f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'Bollinger', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    # ৫. Volume Profile (POC)
    try:
        poc = calculate_volume_profile_poc(df)
        last_price = df['close'].iloc[-1]
        if last_price > poc:
            v = 'BUY'
        elif last_price < poc:
            v = 'SELL'
        else:
            v = 'HOLD'
        vote_items.append({'name': 'Vol Profile', 'vote': v, 'value': f"POC: {poc:.4f}"})
        votes[v] += 1
    except:
        vote_items.append({'name': 'Vol Profile', 'vote': 'HOLD', 'value': 'Error'})
        votes['HOLD'] += 1

    # সিদ্ধান্ত
    if votes['BUY'] >= 3:
        final_signal = 'BUY'
    elif votes['SELL'] >= 3:
        final_signal = 'SELL'
    else:
        final_signal = 'HOLD'

    return final_signal, votes, vote_items

# ============================================================
# ৪. ট্রেন্ড লাইন ডিটেক্টর
# ============================================================
def calculate_trendline_points(df, order=5, lookback=50):
    data = df.tail(lookback).copy()
    data.reset_index(drop=True, inplace=True)
    highs = data['high'].values
    lows = data['low'].values
    
    pivot_lows = []
    for i in range(order, len(data) - order):
        if lows[i] == min(lows[i-order:i+order+1]):
            pivot_lows.append((i, lows[i]))
    pivot_highs = []
    for i in range(order, len(data) - order):
        if highs[i] == max(highs[i-order:i+order+1]):
            pivot_highs.append((i, highs[i]))
    
    uptrend_x, uptrend_y = None, None
    if len(pivot_lows) >= 2:
        p1, p2 = pivot_lows[-2], pivot_lows[-1]
        x1, y1 = p1
        x2, y2 = p2
        if x2 > x1 and y2 > y1:
            slope = (y2 - y1) / (x2 - x1)
            end_x = len(data) - 1
            start_ts = data.loc[x1, 'timestamp']
            end_ts = data.loc[end_x, 'timestamp']
            uptrend_x = [start_ts, end_ts]
            uptrend_y = [y1, y1 + slope * (end_x - x1)]
            if uptrend_y[0] > uptrend_y[1]:
                uptrend_x, uptrend_y = None, None

    downtrend_x, downtrend_y = None, None
    if len(pivot_highs) >= 2:
        p1, p2 = pivot_highs[-2], pivot_highs[-1]
        x1, y1 = p1
        x2, y2 = p2
        if x2 > x1 and y2 < y1:
            slope = (y2 - y1) / (x2 - x1)
            end_x = len(data) - 1
            start_ts = data.loc[x1, 'timestamp']
            end_ts = data.loc[end_x, 'timestamp']
            downtrend_x = [start_ts, end_ts]
            downtrend_y = [y1, y1 + slope * (end_x - x1)]
            if downtrend_y[0] < downtrend_y[1]:
                downtrend_x, downtrend_y = None, None

    return uptrend_x, uptrend_y, downtrend_x, downtrend_y

# ============================================================
# ৫. সাপোর্ট/রেসিস্টেন্স ক্যালকুলেটর
# ============================================================
def calculate_support_resistance(df, lookback=30, num_levels=3):
    try:
        data = df.tail(lookback)
        highs = data['high'].values
        lows = data['low'].values
        pivot_highs = []
        pivot_lows = []
        for i in range(2, len(data)-2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                pivot_highs.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                pivot_lows.append(lows[i])
        def cluster(values, tolerance=0.001):
            if not values: return []
            values = sorted(values)
            clusters = []
            current_cluster = [values[0]]
            for v in values[1:]:
                if abs(v - current_cluster[-1]) / current_cluster[-1] < tolerance:
                    current_cluster.append(v)
                else:
                    clusters.append(np.mean(current_cluster))
                    current_cluster = [v]
            clusters.append(np.mean(current_cluster))
            return clusters
        resistance = cluster(pivot_highs)[-num_levels:] if pivot_highs else []
        support = cluster(pivot_lows)[-num_levels:] if pivot_lows else []
        if len(resistance) < num_levels:
            resistance = [np.percentile(highs, 80), np.percentile(highs, 90), np.percentile(highs, 95)]
        if len(support) < num_levels:
            support = [np.percentile(lows, 20), np.percentile(lows, 10), np.percentile(lows, 5)]
        return support[:num_levels], resistance[:num_levels]
    except:
        return [df['low'].quantile(0.2), df['low'].quantile(0.1), df['low'].quantile(0.05)], \
               [df['high'].quantile(0.8), df['high'].quantile(0.9), df['high'].quantile(0.95)]

# ============================================================
# ৬. চার্ট তৈরির ফাংশন
# ============================================================
def create_candlestick_chart(df, support, resistance, uptrend_line, downtrend_line, title="Price Chart"):
    fig = go.Figure(data=[go.Candlestick(
        x=df['timestamp'], open=df['open'], high=df['high'],
        low=df['low'], close=df['close'], name="Candles"
    )])
    
    for level in support:
        fig.add_hline(y=level, line_dash="dash", line_color="#ff6b6b", opacity=0.8, annotation_text=f"S {level:.8f}")
    for level in resistance:
        fig.add_hline(y=level, line_dash="dash", line_color="#51cf66", opacity=0.8, annotation_text=f"R {level:.8f}")
    
    if uptrend_line is not None:
        x_vals, y_vals = uptrend_line
        fig.add_trace(go.Scatter(x=x_vals, y=y_vals, mode="lines", name="আপট্রেন্ড", line=dict(color="#00d4ff", width=3, dash="dot")))
    if downtrend_line is not None:
        x_vals, y_vals = downtrend_line
        fig.add_trace(go.Scatter(x=x_vals, y=y_vals, mode="lines", name="ডাউনট্রেন্ড", line=dict(color="#ff922b", width=3, dash="dot")))
    
    fig.update_layout(template="plotly_dark", height=550, xaxis_rangeslider_visible=False, title=title)
    return fig

# ============================================================
# ৭. প্রাইস ট্রিগার জোন ডিটেক্টর
# ============================================================
def get_price_trigger_zone(price, support, resistance):
    nearest_support = max([s for s in support if s < price], default=None)
    nearest_resistance = min([r for r in resistance if r > price], default=None)
    
    zone = "NEUTRAL"
    details = ""
    
    if nearest_support:
        diff_pct = abs((price - nearest_support) / price) * 100
        if diff_pct < 1.0:
            zone = "BUY ZONE"
            details = f"দাম নিকটতম সাপোর্ট ({format_price(nearest_support)}) থেকে মাত্র {diff_pct:.2f}% উপরে। এখানে বাউন্সের সম্ভাবনা বেশি।"
        elif diff_pct < 2.0:
            zone = "NEAR SUPPORT"
            details = f"দাম সাপোর্ট ({format_price(nearest_support)}) থেকে {diff_pct:.2f}% উপরে। মনিটর করুন।"
    
    if nearest_resistance:
        diff_pct = abs((nearest_resistance - price) / price) * 100
        if diff_pct < 1.0:
            zone = "SELL ZONE"
            details = f"দাম নিকটতম রেজিস্টেন্স ({format_price(nearest_resistance)}) থেকে মাত্র {diff_pct:.2f}% নিচে। এখানে রিজেক্ট হওয়ার সম্ভাবনা বেশি।"
        elif diff_pct < 2.0:
            zone = "NEAR RESISTANCE"
            details = f"দাম রেজিস্টেন্স ({format_price(nearest_resistance)}) থেকে {diff_pct:.2f}% নিচে। ব্রেকআউট দেখুন।"
    
    if zone == "NEUTRAL":
        details = "দাম সাপোর্ট ও রেজিস্টেন্স থেকে যথেষ্ট দূরে। বর্তমানে কোনো ট্রিগার জোনে নেই।"
    
    return zone, details

# ============================================================
# ৮. ফিউচার ডেটা ফেচ (আপডেটেড)
# ============================================================
@st.cache_data(ttl=300)
def fetch_klines(symbol, interval="1h", limit=100):
    try:
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        df = pd.DataFrame(data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df[['open', 'high', 'low', 'close']] = df[['open', 'high', 'low', 'close']].astype(float)
        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
    except Exception as e:
        return None

def calculate_atr(df, period=14):
    try:
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift())
        tr3 = abs(df['low'] - df['close'].shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(period).mean().iloc[-1]
    except:
        return (df['high'].iloc[-1] - df['low'].iloc[-1]) * 0.5

# ============================================================
# ৯. ফিউচার পেয়ার লোড (আপডেটেড - PERP ফিল্টার বাদ)
# ============================================================
@st.cache_data(ttl=3600)
def get_all_usdt_pairs(min_volume_usdt=500000):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        usdt_pairs = []
        for item in data:
            symbol = item['symbol']
            if symbol.endswith('USDT'):
                # শুধু স্পটের UP/DOWN/BEAR/BULL পেয়ার বাদ দেওয়া হচ্ছে
                if any(x in symbol for x in ['UP', 'DOWN', 'BEAR', 'BULL', 'USDC', 'BUSD', 'DAI', 'TUSD']):
                    continue
                try:
                    volume = float(item['quoteVolume'])
                    if volume < min_volume_usdt:
                        continue
                    usdt_pairs.append({
                        'symbol': symbol,
                        'volume': volume,
                        'price': float(item['lastPrice'])
                    })
                except:
                    continue
        usdt_pairs.sort(key=lambda x: x['volume'], reverse=True)
        return usdt_pairs
    except Exception as e:
        st.error(f"ফিউচার পেয়ার লোড করতে ব্যর্থ: {e}")
        return []

# ============================================================
# ১০. সিগন্যাল জেনারেটর
# ============================================================
def generate_signal(df, current_tf="1h", symbol=None, use_mtf=True):
    try:
        final_signal, votes, vote_items = voting_signal(df)
        
        mtf_score = 0
        if use_mtf and current_tf in ["1h", "2h", "4h"] and symbol:
            try:
                df_h4 = fetch_klines(symbol, interval="4h", limit=50)
                if df_h4 is not None and len(df_h4) > 30:
                    detector = MarketRegimeDetector()
                    regime_h4 = detector.detect(df_h4)
                    if regime_h4 == MarketRegime.BULL: mtf_score += 1
                    elif regime_h4 == MarketRegime.BEAR: mtf_score -= 1
                
                df_d1 = fetch_klines(symbol, interval="1d", limit=30)
                if df_d1 is not None and len(df_d1) > 20:
                    detector = MarketRegimeDetector()
                    regime_d1 = detector.detect(df_d1)
                    if regime_d1 == MarketRegime.BULL: mtf_score += 1
                    elif regime_d1 == MarketRegime.BEAR: mtf_score -= 1
            except:
                pass

        if final_signal == 'BUY' and mtf_score <= -2:
            final_signal = 'HOLD'
        elif final_signal == 'SELL' and mtf_score >= 2:
            final_signal = 'HOLD'

        last_price = df['close'].iloc[-1]
        current_atr = calculate_atr(df)
        
        if final_signal == "SELL":
            stop_loss = last_price + (current_atr * 1.8)
            take_profit = last_price - (current_atr * 3.5)
        else:
            stop_loss = last_price - (current_atr * 1.8)
            take_profit = last_price + (current_atr * 3.5)
        
        tp_percent = abs((take_profit - last_price) / last_price) * 100
        MIN_TP = 3.0
        if tp_percent < MIN_TP:
            if final_signal == "SELL":
                take_profit = last_price * (1 - MIN_TP/100)
            else:
                take_profit = last_price * (1 + MIN_TP/100)
            tp_percent = MIN_TP
        
        if final_signal == "SELL":
            trailing_stop_activation = take_profit
            trailing_stop_price = take_profit + (last_price - take_profit) * 0.4
        else:
            trailing_stop_activation = take_profit
            trailing_stop_price = take_profit - (take_profit - last_price) * 0.4
        
        risk_per_trade = 0.01
        if stop_loss != last_price:
            position_size = risk_per_trade / (abs(last_price - stop_loss) / last_price)
        else:
            position_size = 0.5
        
        detector = MarketRegimeDetector()
        regime = detector.detect(df)
        
        return {
            "signal": final_signal,
            "regime": regime.value,
            "strategy": "majority_voting_5ind",
            "entry_price": last_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "trailing_stop_price": trailing_stop_price,
            "trailing_activation": trailing_stop_activation,
            "position_size": position_size,
            "sl_percent": abs((last_price - stop_loss) / last_price) * 100,
            "tp_percent": tp_percent,
            "reason": f"MTF স্কোর: {mtf_score}",
            "rsi": calculate_rsi(df),
            "votes": votes,
            "vote_items": vote_items
        }
    except Exception as e:
        return {
            "signal": "ERROR", "regime": "error", "strategy": "none",
            "entry_price": 0, "stop_loss": 0, "take_profit": 0,
            "trailing_stop_price": 0, "trailing_activation": 0,
            "position_size": 0.5,
            "sl_percent": 0, "tp_percent": 0,
            "reason": str(e), "rsi": 50,
            "votes": {'BUY':0, 'SELL':0, 'HOLD':5},
            "vote_items": []
        }

# ============================================================
# ১১. মার্কেট স্ক্যানার (প্যারালাল)
# ============================================================
def scan_market(pairs, interval, limit_candles=100, use_mtf=True):
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    total = len(pairs)
    completed = 0

    def process_pair(pair):
        symbol = pair['symbol']
        df = fetch_klines(symbol, interval=interval, limit=limit_candles)
        if df is not None and len(df) > 50:
            sig = generate_signal(df, current_tf=interval, symbol=symbol, use_mtf=use_mtf)
            sup, res = calculate_support_resistance(df)
            entry = sig['entry_price']
            
            supports_below = [s for s in sup if s < entry]
            nearest_support = max(supports_below) if supports_below else sup[-1] if sup else 0
            resistances_above = [r for r in res if r > entry]
            nearest_resistance = min(resistances_above) if resistances_above else res[-1] if res else 0
            
            return {
                'symbol': symbol,
                'price': pair['price'],
                'signal': sig['signal'],
                'entry_price': sig['entry_price'],
                'stop_loss': sig['stop_loss'],
                'take_profit': sig['take_profit'],
                'trailing_stop': sig['trailing_stop_price'],
                'position_size': sig['position_size'],
                'nearest_support': nearest_support,
                'nearest_resistance': nearest_resistance,
                'regime': sig['regime'],
                'rsi': sig['rsi'],
                'reason': sig['reason'],
                'sl_percent': sig['sl_percent'],
                'tp_percent': sig['tp_percent'],
                'votes_buy': sig['votes']['BUY'],
                'votes_sell': sig['votes']['SELL'],
                'votes_hold': sig['votes']['HOLD'],
                'vote_items': sig['vote_items']
            }
        else:
            return {
                'symbol': symbol,
                'price': pair['price'],
                'signal': 'NO DATA',
                'entry_price': 0,
                'stop_loss': 0,
                'take_profit': 0,
                'trailing_stop': 0,
                'position_size': 0,
                'nearest_support': 0,
                'nearest_resistance': 0,
                'regime': '-',
                'rsi': 0,
                'reason': 'ডেটা পাওয়া যায়নি',
                'sl_percent': 0,
                'tp_percent': 0,
                'votes_buy': 0,
                'votes_sell': 0,
                'votes_hold': 0,
                'vote_items': []
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_pair = {executor.submit(process_pair, pair): pair for pair in pairs}
        for future in concurrent.futures.as_completed(future_to_pair):
            result = future.result()
            results.append(result)
            completed += 1
            progress_bar.progress(completed / total)
            status_text.text(f"✅ প্রসেসিং: {completed}/{total} - {result['symbol']}")
    
    status_text.text("✅ স্ক্যান সম্পূর্ণ!")
    return pd.DataFrame(results)

# ============================================================
# ১২. মেইন UI
# ============================================================
st.title("🤖 ক্রিপ্টো ফিউচার সিগন্যাল বট (সিম্পল মেজরিটি ভোট)")
st.markdown("### 📊 ফর্মুলা: BUY≥৩ ➜ BUY | SELL≥৩ ➜ SELL | অন্যথায় HOLD")
st.caption("⚡ Binance Futures (USDT পারপেচুয়াল) — ভলিউম ফিল্টার: ৫০০k+")

st.sidebar.header("⚙️ কন্ট্রোল প্যানেল")

mode = st.sidebar.radio(
    "মোড নির্বাচন করুন",
    ["🔍 সিঙ্গেল কয়েন অ্যানালাইসিস", "📡 মার্কেট স্ক্যানার (সব কয়েন)"]
)

if mode == "🔍 সিঙ্গেল কয়েন অ্যানালাইসিস":
    symbol = st.sidebar.text_input("সিম্বল", value="BTCUSDT")
    timeframe = st.sidebar.selectbox("টাইমফ্রেম", ["1h", "2h", "4h"])
    limit = st.sidebar.slider("ক্যান্ডেল সংখ্যা", 50, 200, 100)
    use_mtf = st.sidebar.checkbox("🔄 MTF কনফার্মেশন (৪h+১D) চালু রাখুন", value=True)
    
    if st.sidebar.button("🚀 সিগন্যাল জেনারেট করো", type="primary"):
        with st.spinner(f"{symbol} এর ডেটা আনছে..."):
            df = fetch_klines(symbol, interval=timeframe, limit=limit)
            if df is not None:
                support, resistance = calculate_support_resistance(df)
                uptrend_x, uptrend_y, downtrend_x, downtrend_y = calculate_trendline_points(df)
                sig = generate_signal(df, current_tf=timeframe, symbol=symbol, use_mtf=use_mtf)
                
                uptrend_line = (uptrend_x, uptrend_y) if uptrend_x is not None else None
                downtrend_line = (downtrend_x, downtrend_y) if downtrend_x is not None else None
                
                zone, zone_details = get_price_trigger_zone(sig['entry_price'], support, resistance)
                
                col1, col2 = st.columns([2, 1])
                with col1:
                    fig = create_candlestick_chart(df, support, resistance, uptrend_line, downtrend_line, f"{symbol} - {timeframe}")
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    vote_text = f"BUY:{sig['votes']['BUY']} / SELL:{sig['votes']['SELL']} / HOLD:{sig['votes']['HOLD']}"
                    
                    zone_style = "zone-neutral"
                    if "BUY ZONE" in zone:
                        zone_style = "zone-buy"
                    elif "SELL ZONE" in zone:
                        zone_style = "zone-sell"
                    
                    st.markdown(f"""
                    <div class="signal-card">
                        <h3 style="margin-top:0;">{symbol}</h3>
                        <p>বর্তমান মূল্য: <b class="full-price">${format_price(sig['entry_price'])}</b></p>
                        <p>সিগন্যাল: <span class="{'buy-badge' if sig['signal']=='BUY' else 'sell-badge' if sig['signal']=='SELL' else 'hold-badge'}">{sig['signal']}</span></p>
                        <p>রেজিম: <b>{sig['regime'].upper()}</b> | ভোট: <b>{vote_text}</b></p>
                        <p>RSI: <b>{sig['rsi']:.1f}</b></p>
                        <hr style="border-color:#2a3a5e;">
                        <div class="{zone_style}" style="margin:8px 0;">
                            <b>📍 প্রাইস ট্রিগার জোন: {zone}</b><br>
                            <span style="font-size:0.8rem;">{zone_details}</span>
                        </div>
                        <hr style="border-color:#2a3a5e;">
                        <div class="price-box">🚀 Buy: <b class="full-price">${format_price(sig['entry_price'])}</b></div>
                        <div class="price-box" style="border-left-color: #ff4444;">🛑 স্টপ-লস: <b class="full-price">${format_price(sig['stop_loss'])}</b> ({sig['sl_percent']:.2f}%)</div>
                        <div class="price-box" style="border-left-color: #00c853;">🎯 টার্গেট: <b class="full-price">${format_price(sig['take_profit'])}</b> ({sig['tp_percent']:.2f}%)</div>
                        <div class="price-box" style="border-left-color: #ffaa00;">⚡ ট্রেইলিং SL: <b class="full-price">${format_price(sig['trailing_stop_price'])}</b></div>
                        <div class="price-box" style="border-left-color: #7b2ffc;">📊 সাইজ: <b>{sig['position_size']:.2f}x</b></div>
                        <p style="color:#b0c4de;font-size:0.8rem;margin-top:10px;">💡 {sig['reason']}</p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    with st.expander("📊 বিস্তারিত ভোট বিশ্লেষণ (ইন্ডিকেটর নাম সহ)"):
                        for item in sig['vote_items']:
                            emoji = "🟢" if item['vote'] == 'BUY' else "🔴" if item['vote'] == 'SELL' else "⚪"
                            st.write(f"{emoji} **{item['name']}**: `{item['vote']}` → {item['value']}")
                    
                    with st.expander("📌 সাপোর্ট/রেজিস্টেন্স ও ট্রেন্ড লাইন"):
                        st.write("🔴 **সাপোর্ট** (এন্ট্রির নিচে):", [format_price(l) for l in support if l < sig['entry_price']])
                        st.write("🟢 **রেজিস্টেন্স** (এন্ট্রির উপরে):", [format_price(l) for l in resistance if l > sig['entry_price']])
                        if uptrend_line is not None:
                            st.success(f"⬆️ **আপট্রেন্ড** সক্রিয় (সর্বশেষ পিভট লো থেকে উঠেছে)")
                        if downtrend_line is not None:
                            st.error(f"⬇️ **ডাউনট্রেন্ড** সক্রিয় (সর্বশেষ পিভট হাই থেকে নেমেছে)")
            else:
                st.error("ফিউচার ডেটা লোড করা যায়নি। সিম্বল চেক করুন (যেমন: BTCUSDT, ETHUSDT)")

else:
    st.markdown("### 📡 লাইভ ফিউচার মার্কেট স্ক্যানার (শুধু BUY/SELL)")
    st.caption("ভলিউম ফিল্টার (৫০০k USDT) + সিম্পল মেজরিটি ভোট (BUY≥৩ বা SELL≥৩)")
    
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        num_coins = st.slider("কতটি কয়েন স্ক্যান করবে?", 10, 600, 100, step=10)
    with col_b:
        scan_tf = st.selectbox("স্ক্যান টাইমফ্রেম", ["1h", "2h", "4h"], index=0)
    with col_c:
        use_mtf_scan = st.checkbox("🔄 MTF ফিল্টার চালু রাখুন", value=True)
    
    if st.button("🔥 স্ক্যান শুরু করো", type="primary"):
        with st.spinner("Binance Futures থেকে সব কয়েন লোড হচ্ছে..."):
            all_pairs = get_all_usdt_pairs(min_volume_usdt=500000)
        
        if all_pairs:
            pairs_to_scan = all_pairs[:num_coins]
            st.info(f"মোট {len(all_pairs)} টি ফিউচার পেয়ার পাওয়া গেছে। স্ক্যান করা হবে: {len(pairs_to_scan)} টি।")
            
            df_results = scan_market(pairs_to_scan, scan_tf, limit_candles=100, use_mtf=use_mtf_scan)
            
            active_signals = df_results[df_results['signal'].isin(['BUY', 'SELL'])]
            
            if not active_signals.empty:
                st.subheader(f"🔥 অ্যাক্টিভ সিগন্যাল ({len(active_signals)} টি)")
                cols = st.columns(3)
                for idx, (_, row) in enumerate(active_signals.head(9).iterrows()):
                    col = cols[idx % 3]
                    badge_class = "buy-badge" if row['signal'] == 'BUY' else "sell-badge"
                    with col:
                        st.markdown(f"""
                        <div class="signal-card" style="border-left-color: {'#00c853' if row['signal']=='BUY' else '#d50000'};">
                            <h4 style="margin:0;">{row['symbol']}</h4>
                            <p style="font-size:0.8rem;color:#b0c4de;">বর্তমান: ${format_price(row['price'])}</p>
                            <span class="{badge_class}">{row['signal']}</span>
                            <span style="margin-left:10px;font-size:0.8rem;">RSI: {row['rsi']:.1f}</span>
                            <span style="margin-left:10px;font-size:0.7rem;background:#2a3a5e;padding:2px 8px;border-radius:10px;">ভোট {int(row['votes_buy'])}/{int(row['votes_sell'])}/{int(row['votes_hold'])}</span>
                            <div style="margin-top:8px;font-size:0.7rem;font-family:monospace;">
                                <div>🚀 Buy: ${format_price(row['entry_price'])}</div>
                                <div style="color:#ff4444;">🛑 SL: ${format_price(row['stop_loss'])}</div>
                                <div style="color:#44ff44;">🎯 TP: ${format_price(row['take_profit'])} ({row['tp_percent']:.2f}%)</div>
                                <hr style="border-color:#2a3a5e;margin:4px 0;">
                                <div>🔴 S: {format_price(row['nearest_support'])} | 🟢 R: {format_price(row['nearest_resistance'])}</div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                
                st.subheader("📋 স্ক্যান রেজাল্ট (শুধু BUY/SELL)")
                display_df = active_signals.copy()
                price_cols = ['price', 'entry_price', 'stop_loss', 'take_profit', 'trailing_stop', 'nearest_support', 'nearest_resistance']
                for col in price_cols:
                    if col in display_df.columns:
                        display_df[col] = display_df[col].apply(lambda x: format_price(x) if x != 0 else "N/A")
                
                display_df['rsi'] = display_df['rsi'].map('{:.1f}'.format)
                display_df['sl_percent'] = display_df['sl_percent'].map('{:.2f}%'.format)
                display_df['tp_percent'] = display_df['tp_percent'].map('{:.2f}%'.format)
                display_df['position_size'] = display_df['position_size'].map('{:.2f}x'.format)
                
                display_df.columns = ['সিম্বল', 'বর্তমান মূল্য', 'সিগন্যাল', 'এন্ট্রি', 'স্টপ-লস', 'টার্গেট', 
                                      'ট্রেইলিং SL', 'পজিশন সাইজ', 'নিকট সাপোর্ট', 'নিকট রেসিস্টেন্স', 
                                      'রেজিম', 'RSI', 'কারণ', 'SL %', 'TP %', 'ভোট BUY', 'ভোট SELL', 'ভোট HOLD', 'ভোট আইটেম']
                
                def color_signal(val):
                    if val == 'BUY':
                        return 'background-color: #00c853; color: black; font-weight: bold;'
                    elif val == 'SELL':
                        return 'background-color: #d50000; color: white; font-weight: bold;'
                    else:
                        return ''
                
                styled = display_df.style.applymap(color_signal, subset=['সিগন্যাল'])
                st.dataframe(styled, use_container_width=True, height=600)
                
                csv = active_signals.to_csv(index=False)
                st.download_button(
                    label="📥 রেজাল্ট CSV ডাউনলোড করো",
                    data=csv,
                    file_name=f"futures_scan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv"
                )
            else:
                st.warning("কোনো BUY বা SELL সিগন্যাল পাওয়া যায়নি (৩টি ভোটের থ্রেশহোল্ড পূরণ হয়নি)।")
        else:
            st.error("কোনো ফিউচার কয়েন পাওয়া যায়নি (ভলিউম কম থাকতে পারে বা API সংযোগ সমস্যা)।")

st.markdown("---")
st.caption("⚠️ **ডিসক্লেইমার**: শিক্ষামূলক টুল। ফিউচার ট্রেডিং অত্যন্ত ঝুঁকিপূর্ণ। নিজের দায়িত্বে ব্যবহার করুন।")