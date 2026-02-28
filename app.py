import streamlit as st
import pandas as pd
import requests
import time
from streamlit_lightweight_charts import renderLightweightCharts

# --- 1. PRO TRADINGVIEW CONFIG ---
st.set_page_config(page_title="Delta Live Pro", layout="wide")

if 'candles' not in st.session_state:
    st.session_state.candles = []

# --- 2. THE BYPASS ENGINE (Sub-Second Polling) ---
def fetch_live_price(symbol):
    url = f"https://api.india.delta.exchange/v2/tickers/{symbol}"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res['result']['mark_price'])
    except: return None

# --- 3. UI CONTROLS ---
with st.sidebar:
    st.header("🎛️ Terminal Settings")
    symbol = st.selectbox("Select Market", ["BTCUSD", "ETHUSD", "SOLUSD"])
    # Set to 500ms for "Tick-by-Tick" feel without crashing
    speed = st.slider("Refresh Speed (ms)", 100, 2000, 500)

# Fetch Current Data
price = fetch_live_price(symbol)

if price:
    # Use standard Unix timestamp for TradingView compatibility
    ts = int(time.time())
    
    # Update or Create Candle
    if st.session_state.candles and st.session_state.candles[-1]['time'] == ts:
        st.session_state.candles[-1]['high'] = max(st.session_state.candles[-1]['high'], price)
        st.session_state.candles[-1]['low'] = min(st.session_state.candles[-1]['low'], price)
        st.session_state.candles[-1]['close'] = price
    else:
        new_candle = {'time': ts, 'open': price, 'high': price, 'low': price, 'close': price}
        st.session_state.candles.append(new_candle)
        if len(st.session_state.candles) > 60: st.session_state.candles.pop(0)

    # --- 4. RENDER TRADINGVIEW INTERFACE ---
    chart_options = {
        "layout": {"background": {"color": "#131722"}, "textColor": "#d1d4dc"},
        "grid": {"vertLines": {"color": "#1e222d"}, "horzLines": {"color": "#1e222d"}},
        "timeScale": {"timeVisible": True, "secondsVisible": True}
    }
    
    chart_series = [{
        "type": "Candlestick",
        "data": st.session_state.candles,
        "options": {
            "upColor": "#26a69a", "downColor": "#ef5350",
            "borderUpColor": "#26a69a", "borderDownColor": "#ef5350",
            "wickUpColor": "#26a69a", "wickDownColor": "#ef5350",
        }
    }]

    st.markdown(f"<h2 style='color:white;'>{symbol}: ₹{price:,.2f}</h2>", unsafe_allow_html=True)
    renderLightweightCharts([{"options": chart_options, "series": chart_series}], "main_chart")

# --- 5. THE LIVE HEARTBEAT ---
time.sleep(speed / 1000)
st.rerun()
