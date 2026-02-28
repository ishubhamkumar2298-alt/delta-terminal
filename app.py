import streamlit as st
import pandas as pd
import requests
import time
import plotly.graph_objects as go

st.set_page_config(page_title="Delta Mobile Terminal", layout="wide")

# Persistent State
if 'price_history' not in st.session_state:
    st.session_state.price_history = []
if 'start_time' not in st.session_state:
    st.session_state.start_time = time.time()

# --- THE BYPASS ENGINE ---
def get_delta_price():
    # Calling the public REST API (Works better on 5G than WebSockets)
    url = "https://api.india.delta.exchange/v2/tickers/BTCUSD"
    try:
        res = requests.get(url, timeout=5).json()
        price = float(res['result']['mark_price'])
        return price
    except Exception as e:
        return None

# --- UI ---
st.title("🏛️ Delta India Mobile")

# Timer
elapsed = int(time.time() - st.session_state.start_time)
st.sidebar.metric("System Uptime", f"{elapsed}s")

# Data Fetching
current_p = get_delta_price()

if current_p:
    st.session_state.ws_status = "Bypass Active 🔵"
    st.session_state.price_history.append({'t': pd.Timestamp.now(), 'p': current_p})
    if len(st.session_state.price_history) > 30: st.session_state.price_history.pop(0)
    
    st.metric("BTCUSD Price (REST)", f"₹{current_p:,.2f}")
    
    # Charting
    df = pd.DataFrame(st.session_state.price_history)
    fig = go.Figure(go.Scatter(x=df['t'], y=df['p'], mode='lines+markers', line=dict(color='#00ff00')))
    fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0,r=0,t=0,b=0))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.error("Network still blocking API. Try turning on 'Data Saver' or check your 5G signal.")

# Force update every 2 seconds
time.sleep(2)
st.rerun()
