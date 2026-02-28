import streamlit as st
import pandas as pd
import requests
import time

# --- 1. PRO TERMINAL LAYOUT ---
st.set_page_config(page_title="Delta Pro Quant", layout="wide")

# Custom Styling to match the TradingView 'Dark Mode'
st.markdown("""
    <style>
    .main { background-color: #131722; }
    [data-testid="stHeader"] { background-color: #131722; }
    [data-testid="stMetricValue"] { color: #00ff00 !important; font-size: 32px; }
    div.block-container { padding-top: 1rem; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. THE TOP BAR (INSTRUMENT & TIMEFRAME) ---
# This puts selectors on the main page, not the sidebar
col1, col2, col3 = st.columns([2, 2, 8])

with col1:
    symbol = st.selectbox("Symbol", ["BTCUSD", "ETHUSD", "SOLUSD"], label_visibility="collapsed")
with col2:
    timeframe = st.selectbox("Time", ["1m", "5m", "15m", "1H"], label_visibility="collapsed")

# --- 3. THE LIVE ENGINE ---
def fetch_now(s):
    url = f"https://api.india.delta.exchange/v2/tickers/{s}"
    try:
        res = requests.get(url, timeout=2).json()
        return float(res['result']['mark_price'])
    except: return None

# Initialize OHLC history
if 'ohlc' not in st.session_state:
    st.session_state.ohlc = []

price = fetch_now(symbol)

if price:
    ts = int(time.time())
    # Simple logic to build candles from live ticks
    if st.session_state.ohlc and st.session_state.ohlc[-1]['time'] == ts:
        st.session_state.ohlc[-1]['close'] = price
    else:
        st.session_state.ohlc.append({'time': ts, 'open': price, 'high': price, 'low': price, 'close': price})
        if len(st.session_state.ohlc) > 60: st.session_state.ohlc.pop(0)

    # Display Price Metric like a real ticker
    st.metric(label=f"{symbol} • {timeframe}", value=f"₹{price:,.2f}")

    # --- 4. THE CHART (Using Plotly for high-speed interaction) ---
    import plotly.graph_objects as go
    
    fig = go.Figure(data=[go.Candlestick(
        x=[pd.to_datetime(d['time'], unit='s') for d in st.session_state.ohlc],
        open=[d['open'] for d in st.session_state.ohlc],
        high=[d['high'] for d in st.session_state.ohlc],
        low=[d['low'] for d in st.session_state.ohlc],
        close=[d['close'] for d in st.session_state.ohlc],
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    )])

    fig.update_layout(
        template="plotly_dark", height=600,
        xaxis_rangeslider_visible=False,
        paper_bgcolor='#131722', plot_bgcolor='#131722',
        margin=dict(l=0, r=0, t=0, b=0)
    )
    
    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

# --- 5. HEARTBEAT REFRESH ---
time.sleep(0.5)
st.rerun()
