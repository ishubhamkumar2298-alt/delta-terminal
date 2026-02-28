import streamlit as st
import pandas as pd
import json, websocket, threading, time
import plotly.graph_objects as go

# --- 1. TERMINAL CONFIG ---
st.set_page_config(page_title="Delta India Quant", layout="wide")

# Persistent Storage
if 'logs' not in st.session_state: st.session_state.logs = ["System Initialized"]
if 'price_history' not in st.session_state: st.session_state.price_history = []
if 'ws_status' not in st.session_state: st.session_state.ws_status = "Disconnected 🔴"

def log(msg):
    st.session_state.logs.append(f"{pd.Timestamp.now().strftime('%H:%M:%S')} - {msg}")
    if len(st.session_state.logs) > 5: st.session_state.logs.pop(0)

# --- 2. THE WEBSOCKET ENGINE ---
def on_message(ws, message):
    data = json.loads(message)
    if 'type' in data and data['type'] == 'v2/ticker':
        st.session_state.ws_status = "Connected 🟢"
        price = float(data['mark_price'])
        st.session_state.live_p = price
        st.session_state.price_history.append({'time': pd.Timestamp.now(), 'price': price})
        if len(st.session_state.price_history) > 50: st.session_state.price_history.pop(0)

def run_connection():
    while True:
        try:
            # Explicit India Endpoint
            ws_url = "wss://socket.india.delta.exchange"
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=on_message,
                on_error=lambda ws, e: log(f"Socket Error: {e}"),
                on_close=lambda ws, a, b: setattr(st.session_state, 'ws_status', "Disconnected 🔴")
            )
            def on_open(ws):
                log("Handshake Sent to Delta India")
                # Exact payload for public ticker data
                sub_msg = {"type": "subscribe", "payload": {"channels": [{"name": "v2/ticker", "symbols": ["BTCUSD"]}]}}
                ws.send(json.dumps(sub_msg))
            
            ws.on_open = on_open
            ws.run_forever(ping_interval=20) # Prevents mobile timeout
        except Exception as e:
            log(f"Connection Failed: {e}")
        time.sleep(5) # Cooldown before reconnect

if 'bg_thread' not in st.session_state:
    st.session_state.bg_thread = threading.Thread(target=run_connection, daemon=True)
    st.session_state.bg_thread.start()

# --- 3. THE INTERFACE ---
st.title("🏛️ Delta India Live Terminal")
st.subheader(f"Status: {st.session_state.ws_status}")

# Debug Console
with st.expander("Show System Logs"):
    for l in reversed(st.session_state.logs):
        st.text(l)

# Price Display
live_price = st.session_state.get('live_p', 0.0)
if live_price > 0:
    st.metric("BTCUSD Price", f"₹{live_price:,.2f}")
    
    df = pd.DataFrame(st.session_state.price_history)
    fig = go.Figure(go.Scatter(x=df['time'], y=df['price'], mode='lines+markers', line=dict(color='#00ff00', width=2)))
    fig.update_layout(template="plotly_dark", height=450, margin=dict(l=10,r=10,t=10,b=10))
    st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    st.subheader("🛠️ The Forge Logic")
    st.info("The math below is currently checking Order Flow Balance. Once live, this line will track whale walls.")
    st.code("""
# Indicator Math (Example)
imbalance = (buy_volume - sell_volume) / (total_volume)
indicator_value = imbalance * 100
    """, language="python")
else:
    st.warning("Listening for BTCUSD signals from Delta India. Please keep this tab active.")
    st.progress(st.session_state.get('wait_timer', 0))
