import streamlit as st
import pandas as pd
import json, websocket, threading, time

st.set_page_config(page_title="Delta Debug Terminal", layout="wide")

# Initialize Session State
if 'logs' not in st.session_state: st.session_state.logs = []
if 'start_time' not in st.session_state: st.session_state.start_time = time.time()
if 'ws_status' not in st.session_state: st.session_state.ws_status = "Disconnected 🔴"

def log_event(msg):
    timestamp = pd.Timestamp.now().strftime('%H:%M:%S')
    st.session_state.logs.append(f"[{timestamp}] {msg}")
    if len(st.session_state.logs) > 10: st.session_state.logs.pop(0)

def on_message(ws, message):
    data = json.loads(message)
    if 'type' in data and data['type'] == 'v2/ticker':
        st.session_state.ws_status = "Connected 🟢"
        st.session_state.last_tick = time.time()
        st.session_state.live_price = float(data['mark_price'])

def run_ws():
    log_event("Attempting Handshake with Delta India...")
    while True:
        try:
            ws = websocket.WebSocketApp(
                "wss://socket.india.delta.exchange",
                on_message=on_message,
                on_error=lambda ws, e: log_event(f"Network Error: {e}"),
                on_close=lambda ws, a, b: setattr(st.session_state, 'ws_status', "Disconnected 🔴")
            )
            def on_open(ws):
                log_event("Door Opened! Sending BTCUSD Subscription...")
                sub = {"type": "subscribe", "payload": {"channels": [{"name": "v2/ticker", "symbols": ["BTCUSD"]}]}}
                ws.send(json.dumps(sub))
            ws.on_open = on_open
            ws.run_forever(ping_interval=10)
        except Exception as e:
            log_event(f"Crash: {e}. Retrying in 5s...")
            time.sleep(5)

if 'bg_thread' not in st.session_state:
    threading.Thread(target=run_ws, daemon=True).start()
    st.session_state.bg_thread = True

# --- UI DISPLAY ---
st.title("🏛️ Delta India Debugger")

# Timer Logic
elapsed = int(time.time() - st.session_state.start_time)
col1, col2 = st.columns(2)
col1.metric("Connection Status", st.session_state.ws_status)
col2.metric("Elapsed Time", f"{elapsed}s", help="Time since the app started trying to connect.")

# Debug Logs
with st.expander("🔍 Detailed System Logs (Check here for errors)", expanded=True):
    for entry in reversed(st.session_state.logs):
        st.text(entry)

# Live Price
price = st.session_state.get('live_price', 0.0)
if price > 0:
    st.success(f"SUCCESS: BTCUSD at ₹{price:,.2f}")
    st.balloons()
else:
    st.warning("Still waiting for data... check the logs above for 'Network Error'.")

# Auto-refresh the UI every 2 seconds to update the timer
time.sleep(2)
st.rerun()
