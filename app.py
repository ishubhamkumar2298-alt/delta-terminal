import streamlit as st
import pandas as pd
import json
import websocket
import threading
import time
import plotly.graph_objects as go

st.set_page_config(page_title="Delta Debugger", layout="wide")

# --- 1. THE ENGINE ---
if 'price_history' not in st.session_state:
    st.session_state.price_history = pd.DataFrame(columns=['time', 'price'])
if 'ws_status' not in st.session_state:
    st.session_state.ws_status = "Disconnected 🔴"

def on_message(ws, message):
    data = json.loads(message)
    if 'type' in data and data['type'] == 'v2/ticker':
        st.session_state.ws_status = "Connected 🟢"
        p = float(data['mark_price'])
        st.session_state.current_price = p
        new_row = pd.DataFrame([{'time': pd.Timestamp.now(), 'price': p}])
        st.session_state.price_history = pd.concat([st.session_state.price_history, new_row], ignore_index=True).tail(50)

def start_ws():
    # Use the specific India Delta endpoint
    ws = websocket.WebSocketApp("wss://socket.india.delta.exchange", 
                                on_message=on_message,
                                on_error=lambda ws, e: setattr(st.session_state, 'ws_status', f"Error 🔴: {e}"))
    def on_open(ws):
        # Subscription for BTCUSD
        msg = {"type": "subscribe", "payload": {"channels": [{"name": "v2/ticker", "symbols": ["BTCUSD"]}]}}
        ws.send(json.dumps(msg))
    ws.on_open = on_open
    ws.run_forever()

if 'ws_thread' not in st.session_state:
    st.session_state.ws_thread = threading.Thread(target=start_ws, daemon=True)
    st.session_state.ws_thread.start()

# --- 2. THE UI ---
st.title("🏛️ Delta India Live Terminal")
st.subheader(f"Status: {st.session_state.ws_status}")

price = st.session_state.get('current_price', 0.0)
if price > 0:
    st.metric("BTCUSD Price", f"₹{price:,.2f}")
    df = st.session_state.price_history
    fig = go.Figure(go.Scatter(x=df['time'], y=df['price'], mode='lines+markers', line=dict(color='#00ff00')))
    fig.update_layout(template="plotly_dark", height=400)
    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("Attempting to connect to Delta India... If this stays for 30s, check if BTCUSD is trading.")
