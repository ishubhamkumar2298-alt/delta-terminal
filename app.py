import streamlit as st
import pandas as pd
import requests
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. CONFIG & STYLING ---
st.set_page_config(page_title="Delta Pro Quant", layout="wide")
st.markdown("""
    <style>
    .main { background-color: #131722; color: #d1d4dc; }
    div[data-testid="stSidebar"] { background-color: #1e222d; border-right: 1px solid #363c4e; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. DATA ENGINE ---
if 'history' not in st.session_state:
    st.session_state.history = pd.DataFrame(columns=['Time', 'Open', 'High', 'Low', 'Close', 'Vol'])

def fetch_delta_data(symbol):
    url = f"https://api.india.delta.exchange/v2/tickers/{symbol}"
    try:
        res = requests.get(url, timeout=5).json()
        data = res['result']
        return {
            'price': float(data['mark_price']),
            '24h_vol': float(data['quotes']['volume_24h'])
        }
    except: return None

# --- 3. SIDEBAR: INSTRUMENT & LOGIC ---
st.sidebar.title("🛠️ Terminal Control")
symbol = st.sidebar.selectbox("Market", ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD"])
timeframe = st.sidebar.select_slider("Timeframe", options=["1m", "5m", "15m"])

st.sidebar.markdown("---")
st.sidebar.subheader("📝 Indicator Compiler")
custom_math = st.sidebar.text_area("Python Math (use 'df' for data):", value="""# Simple Moving Average
df['Indicator'] = df['Close'].rolling(window=5).mean()
""", height=200)

# --- 4. PROCESSING ---
raw = fetch_delta_data(symbol)

if raw:
    # Update Local OHLCV (1-minute bars simplified)
    ts = pd.Timestamp.now().floor('min')
    price = raw['price']
    
    if not st.session_state.history.empty and st.session_state.history.iloc[-1]['Time'] == ts:
        # Update current candle
        idx = st.session_state.history.index[-1]
        st.session_state.history.at[idx, 'High'] = max(st.session_state.history.at[idx, 'High'], price)
        st.session_state.history.at[idx, 'Low'] = min(st.session_state.history.at[idx, 'Low'], price)
        st.session_state.history.at[idx, 'Close'] = price
    else:
        # Create new candle
        new_candle = {'Time': ts, 'Open': price, 'High': price, 'Low': price, 'Close': price, 'Vol': raw['24h_vol']}
        st.session_state.history = pd.concat([st.session_state.history, pd.DataFrame([new_candle])], ignore_index=True).tail(100)

    # 5. RUN CUSTOM INDICATOR
    df = st.session_state.history.copy()
    try:
        exec(custom_math)
    except Exception as e:
        st.sidebar.error(f"Logic Error: {e}")

    # --- 6. TRADINGVIEW INTERFACE ---
    st.title(f"📊 {symbol} • {timeframe} Terminal")
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.03)

    # Main Candlestick Chart
    fig.add_trace(go.Candlestick(
        x=df['Time'], open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="Price", increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    ), row=1, col=1)

    # Custom Indicator Overlay
    if 'Indicator' in df.columns:
        fig.add_trace(go.Scatter(x=df['Time'], y=df['Indicator'], name="Custom Logic", line=dict(color='#2962ff', width=2)), row=1, col=1)

    # Volume / Order Flow Bars
    fig.add_trace(go.Bar(x=df['Time'], y=df['Vol'], name="Volume", marker_color='#363c4e'), row=2, col=1)

    fig.update_layout(
        template="plotly_dark", height=800,
        xaxis_rangeslider_visible=False,
        paper_bgcolor='#131722', plot_bgcolor='#131722',
        margin=dict(l=10, r=10, t=10, b=10)
    )
    
    st.plotly_chart(fig, use_container_width=True)
    st.metric("Last Price", f"₹{price:,.2f}", delta=f"{timeframe} bar tracking")

# Loop refresh
time.sleep(2)
st.rerun()
