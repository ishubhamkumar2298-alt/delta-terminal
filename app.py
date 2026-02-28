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
        st.session_state.price_history = pd.concat([st.session_state.price_history, new_p], ignore_index=True).tail(100)
    elif 'type' in data and data['type'] == 'l2_orderbook':
        st.session_state.bids = data.get('buy', [])
        st.session_state.asks = data.get('sell', [])

def start_ws(symbol):
    def run():
        ws = websocket.WebSocketApp("wss://socket.india.delta.exchange", on_message=on_message)
        ws.on_open = lambda ws: ws.send(json.dumps({"type": "subscribe", "payload": {"channels": [{"name": "v2/ticker", "symbols": [symbol]}, {"name": "l2_orderbook", "symbols": [symbol]}]}}))
        ws.run_forever()
    threading.Thread(target=run, daemon=True).start()

# --- 5. UI SIDEBAR & FORGE ---
st.sidebar.title("🏛️ DELTA QUANT")
symbol = st.sidebar.selectbox("Select Market", all_symbols)

if 'current_symbol' not in st.session_state or st.session_state.current_symbol != symbol:
    st.session_state.current_symbol = symbol
    st.session_state.price_history = pd.DataFrame(columns=['time', 'price'])
    st.session_state.indicator_history = pd.DataFrame(columns=['time', 'value'])
    start_ws(symbol)

st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ THE FORGE")
user_code = st.sidebar.text_area("Indicator Logic:", value="""# Math: Buy Vol vs Sell Vol
buy_vol = sum([float(o['size']) for o in bids[:10]])
sell_vol = sum([float(o['size']) for o in asks[:10]])

if (buy_vol + sell_vol) > 0:
    indicator_value = ((buy_vol - sell_vol) / (buy_vol + sell_vol)) * 100
else:
    indicator_value = 0
""", height=250)

# --- 6. LIVE DISPLAY ---
placeholder = st.empty()

while True:
    with placeholder.container():
        price = st.session_state.get('current_price', 0.0)
        bids = st.session_state.bids
        asks = st.session_state.asks
        
        # Execute Forge Math
        indicator_value = 0.0
        try:
            exec(user_code, {}, {'bids': bids, 'asks': asks, 'price': price, 'indicator_value': indicator_value})
            local_vars = locals()
            val = local_vars.get('indicator_value', 0)
            new_i = pd.DataFrame([{'time': pd.Timestamp.now(), 'value': val}])
            st.session_state.indicator_history = pd.concat([st.session_state.indicator_history, new_i], ignore_index=True).tail(100)
        except: pass

        st.header(f"{symbol}: ₹{price:,.2f}")
        
        df_p = st.session_state.price_history
        df_i = st.session_state.indicator_history
        
        if not df_p.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
            # Price Trace
            fig.add_trace(go.Scatter(x=df_p['time'], y=df_p['price'], name="Price", line=dict(color='#00ff00')), row=1, col=1)
            # Forge Trace
            if not df_i.empty:
                fig.add_trace(go.Scatter(x=df_i['time'], y=df_i['value'], name="Forge", line=dict(color='#ff9800')), row=2, col=1)
            
            fig.update_layout(template="plotly_dark", height=600, margin=dict(l=10, r=10, t=10, b=10), showlegend=False)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Waiting for first market tick... Make sure the market is active.")
            
    time.sleep(1)
