import streamlit as st
import pandas as pd
import requests
import time
from streamlit_lightweight_charts import renderLightweightCharts

# --- 1. PRO TRADINGVIEW SETUP ---
st.set_page_config(page_title="Delta Live Quant", layout="wide")

# Persistent Candle Storage
if 'candles' not in st.session_state:
    st.session_state.candles = []

# --- 2. THE LIVE ENGINE (Sub-Second Polling) ---
def fetch_now(symbol):
    url = f"https://api.india.delta.exchange/v2/tickers/{symbol}"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res['result']['mark_price'])
    except: return None

# --- 3. UI CONTROLS ---
symbol = st.sidebar.selectbox("Market", ["BTCUSD", "ETHUSD", "SOLUSD"])
# This allows for sub-second updates
update_speed = st.sidebar.slider("Refresh (ms)", 100, 2000, 500) 

# Fetch Price
price = fetch_now(symbol)

if price:
    ts = int(time.time())
    new_candle = {'time': ts, 'open': price, 'high': price, 'low': price, 'close': price}
    
    # Update or Add Candle
    if st.session_state.candles and st.session_state.candles[-1]['time'] == ts:
        st.session_state.candles[-1]['close'] = price
    else:
        st.session_state.candles.append(new_candle)
        if len(st.session_state.candles) > 50: st.session_state.candles.pop(0)

    # --- 4. TRADINGVIEW LIGHTWEIGHT CHART ---
    chart_options = {
        "layout": {"background": {"color": "#131722"}, "textColor": "#d1d4dc"},
        "grid": {"vertLines": {"color": "#363c4e"}, "horzLines": {"color": "#363c4e"}},
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

    st.subheader(f"LIVE {symbol}: ₹{price:,.2f}")
    renderLightweightCharts([{"options": chart_options, "series": chart_series}], "main_chart")

# --- 5. THE "HEARTBEAT" REFRESH ---
# This forces the page to wake up without the "Blank Screen" flickering
time.sleep(update_speed / 1000)
st.rerun()
