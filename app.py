import streamlit as st
import pandas as pd
import requests
import json
import websocket
import threading
import time
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# --- 1. TERMINAL STYLING (TradingView Look) ---
st.set_page_config(page_title="Delta Universal Quant", layout="wide")
st.markdown("""
    <style>
    .main { background-color: #131722; color: white; }
    div[data-testid="stSidebar"] { background-color: #1e222d; border-right: 1px solid #363c4e; }
    .stTextArea textarea { background-color: #1e222d; color: #00ff00; font-family: monospace; }
    </style>
    """, unsafe_allow_index=True)

# --- 2. DYNAMIC INSTRUMENT DISCOVERY ---
@st.cache_data(ttl=3600)
def get_all_delta_symbols():
    url = "https://api.india.delta.exchange/v2/products"
    try:
        response = requests.get(url).json()
        symbols = [item['symbol'] for item in response['result'] if item['state'] == 'live']
        return sorted(symbols)
    except Exception:
        return ["BTCUSD", "ETHUSD"]

all_symbols = get_all_delta_symbols()

# --- 3. SESSION STATE (Background Memory) ---
if 'price_history' not in st.session_state:
    st.session_state.price_history = pd.DataFrame(columns=['time', 'price'])
if 'indicator_history' not in st.session_state:
    st.session_state.indicator_history = pd.DataFrame(columns=['time', 'value'])
if 'bids' not in st.session_state:
    st.session_state.bids = []
if 'asks' not in st.session_state:
    st.session_state.asks = []
if 'current_symbol' not in st.session_state:
    st.session_state.current_symbol = "BTCUSD"

# --- 4. THE LIVE WEBSOCKET ENGINE ---
def on_message(ws, message):
    data = json.loads(message)
    # Ticker Update (Price)
    if 'type' in data and data['type'] == 'v2/ticker':
        st.session_state.current_price = float(data['mark_price'])
        new_row = {'time': pd.Timestamp.now(), 'price': st.session_state.current_price}
        st.session_state.price_history = pd.concat([st.session_state.price_history, pd.DataFrame([new_row])], ignore_index=True).tail(100)
    # L2 Orderbook Update (Whale Walls)
    elif 'type' in data and data['type'] == 'l2_orderbook':
        st.session_state.bids = data.get('buy', [])
        st.session_state.asks = data.get('sell', [])

def start_websocket(symbol):
    ws_url = "wss://socket.india.delta.exchange"
    ws = websocket.WebSocketApp(ws_url, on_message=on_message)
    def run():
        ws.run_forever()
        sub_msg = {
            "type": "subscribe",
            "payload": {
                "channels": [
                    {"name": "v2/ticker", "symbols": [symbol]},
                    {"name": "l2_orderbook", "symbols": [symbol]}
                ]
            }
        }
        ws.send(json.dumps(sub_msg))
    threading.Thread(target=run, daemon=True).start()

# --- 5. THE UI SIDEBAR ---
st.sidebar.title("🏛️ DELTA QUANT")
default_idx = all_symbols.index(st.session_state.current_symbol) if st.session_state.current_symbol in all_symbols else 0
selected_symbol = st.sidebar.selectbox("Select Market", all_symbols, index=default_idx)

# Switch logic
if selected_symbol != st.session_state.current_symbol:
    st.session_state.current_symbol = selected_symbol
    st.session_state.price_history = pd.DataFrame(columns=['time', 'price'])
    st.session_state.indicator_history = pd.DataFrame(columns=['time', 'value'])
    start_websocket(selected_symbol)

if 'ws_started' not in st.session_state:
    start_websocket(st.session_state.current_symbol)
    st.session_state.ws_started = True

st.sidebar.markdown("---")
st.sidebar.subheader("🛠️ THE FORGE")
user_code = st.sidebar.text_area("Indicator Logic (Python):", value="""# Orderflow Imbalance Math
top_bids = sum([float(order['size']) for order in bids[:10]])
top_asks = sum([float(order['size']) for order in asks[:10]])

if (top_bids + top_asks) > 0:
    indicator_value = ((top_bids - top_asks) / (top_bids + top_asks)) * 100
else:
    indicator_value = 0
""", height=300)

# --- 6. THE LIVE CHARTING ---
chart_placeholder = st.empty()

while True:
    with chart_placeholder.container():
        bids = st.session_state.bids
        asks = st.session_state.asks
        price = getattr(st.session_state, 'current_price', 0.0)
        
        # Execute the Forge Logic
        indicator_value = 0.0
        try:
            exec(user_code, {}, {'bids': bids, 'asks': asks, 'price': price, 'indicator_value': indicator_value})
            local_vars = locals()
            new_ind = {'time': pd.Timestamp.now(), 'value': local_vars.get('indicator_value', 0)}
            st.session_state.indicator_history = pd.concat([st.session_state.indicator_history, pd.DataFrame([new_ind])], ignore_index=True).tail(100)
        except Exception as e:
            st.sidebar.error(f"Forge Error: {e}")

        # Plotting
        df_p = st.session_state.price_history
        df_i = st.session_state.indicator_history
        
        st.markdown(f"<h2 style='color:#00c805;'>{selected_symbol}: ₹{price:,.2f}</h2>", unsafe_allow_index=True)
        
        if not df_p.empty and not df_i.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
            # Price Chart
            fig.add_trace(go.Scatter(x=df_p['time'], y=df_p['price'], mode='lines', line=dict(color='#26a69a', width=2)), row=1, col=1)
            # Indicator Chart
            fig.add_trace(go.Scatter(x=df_i['time'], y=df_i['value'], mode='lines', line=dict(color='#ff9800', width=2)), row=2, col=1)
            
            fig.update_layout(
                template="plotly_dark", height=700,
                paper_bgcolor='#131722', plot_bgcolor='#131722',
                margin=dict(t=10, b=10, l=10, r=10), showlegend=False
            )
            st.plotly_chart(fig, use_container_width=True)
            
    time.sleep(1)
