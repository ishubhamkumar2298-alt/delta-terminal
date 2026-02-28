import streamlit as st
import pandas as pd
import requests
import json
import websocket
import threading
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. SETUP ---
st.set_page_config(page_title="Delta Terminal", layout="wide")

# --- 2. GET SYMBOLS ---
@st.cache_data(ttl=3600)
def get_symbols():
    url = "https://api.india.delta.exchange/v2/products"
    try:
        res = requests.get(url).json()
        return sorted([i['symbol'] for i in res['result'] if i['state'] == 'live'])
    except:
        return ["BTCUSD", "ETHUSD"]

all_symbols = get_symbols()

# --- 3. SESSION STATE ---
if 'price_history' not in st.session_state:
    st.session_state.price_history = pd.DataFrame(columns=['time', 'price'])
if 'indicator_history' not in st.session_state:
    st.session_state.indicator_history = pd.DataFrame(columns=['time', 'value'])
if 'bids' not in st.session_state:
    st.session_state.bids = []
if 'asks' not in st.session_state:
    st.session_state.asks = []

# --- 4. WEBSOCKET ---
def on_message(ws, message):
    data = json.loads(message)
    if 'type' in data and data['type'] == 'v2/ticker':
        price = float(data['mark_price'])
        st.session_state.current_price = price
        new_p = pd.DataFrame([{'time': pd.Timestamp.now(), 'price': price}])
        st.session_state.price_history = pd.concat([st.session_state.price_history, new_p], ignore_index=True).tail(50)
    elif 'type' in data and data['type'] == 'l2_orderbook':
        st.session_state.bids = data.get('buy', [])
        st.session_state.asks = data.get('sell', [])

def start_ws(symbol):
    def run():
        ws = websocket.WebSocketApp("wss://socket.india.delta.exchange", on_message=on_message)
        ws.on_open = lambda ws: ws.send(json.dumps({"type": "subscribe", "payload": {"channels": [{"name": "v2/ticker", "symbols": [symbol]}, {"name": "l2_orderbook", "symbols": [symbol]}]}}))
        ws.run_forever()
    threading.Thread(target=run, daemon=True).start()

# --- 5. UI ---
st.title("🏛️ Delta Professional Terminal")
symbol = st.selectbox("Select Market", all_symbols)

if 'current_symbol' not in st.session_state or st.session_state.current_symbol != symbol:
    st.session_state.current_symbol = symbol
    st.session_state.price_history = pd.DataFrame(columns=['time', 'price'])
    start_ws(symbol)

# --- 6. CHARTING ---
placeholder = st.empty()
while True:
    with placeholder.container():
        price = st.session_state.get('current_price', 0)
        st.metric("Live Price", f"₹{price:,.2f}")
        
        df = st.session_state.price_history
        if not df.empty:
            fig = go.Figure(go.Scatter(x=df['time'], y=df['price'], mode='lines+markers', line=dict(color='#00ff00')))
            fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
            
        # Display simplified Orderbook
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Bids (Buyers)")
            st.write(st.session_state.bids[:5])
        with col2:
            st.subheader("Asks (Sellers)")
            st.write(st.session_state.asks[:5])
            
    time.sleep(2)
