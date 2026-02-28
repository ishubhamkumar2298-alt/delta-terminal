import json
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Any, List, Optional, Tuple

import requests
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from streamlit_lightweight_charts import renderLightweightCharts

import websocket  # websocket-client


# -----------------------------
# Delta endpoints (India)
# -----------------------------
DELTA_REST = "https://api.india.delta.exchange"
DELTA_WS = "wss://socket.india.delta.exchange"


# Supported candle resolutions for WebSocket candlestick_{resolution}
# and REST /history/candles (per Delta docs).
RESOLUTIONS = ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "1w"]


# -----------------------------
# UI / Page config
# -----------------------------
st.set_page_config(page_title="Delta TV (Public Data)", layout="wide", initial_sidebar_state="collapsed")

st.markdown(
    """
<style>
/* Hide Streamlit header */
[data-testid="stHeader"] { visibility: hidden; height: 0; }

/* Tight container padding (more app-like) */
.block-container { padding-top: 0.75rem; padding-bottom: 0.25rem; padding-left: 0.75rem; padding-right: 0.75rem; }

/* Dark selectbox styling */
div[data-baseweb="select"] > div {
  background-color: #131722;
  color: #d1d4dc;
  border-color: #363c4e;
  border-radius: 6px;
}

/* Make buttons more "terminal-like" */
.stButton > button {
  border-radius: 8px;
  border: 1px solid #363c4e;
}

/* App background hint (Streamlit still owns full page background) */
</style>
""",
    unsafe_allow_html=True,
)


# -----------------------------
# Helpers: REST
# -----------------------------
@st.cache_data(ttl=300, show_spinner=False)
def fetch_all_live_products(contract_types: str = "all") -> List[Dict[str, Any]]:
    """
    Pulls ALL live products using cursor pagination.
    Delta uses cursor-based pagination with meta.after/meta.before.
    """
    results: List[Dict[str, Any]] = []
    after = None
    session = requests.Session()

    while True:
        params = {"states": "live", "page_size": 100}
        if contract_types != "all":
            params["contract_types"] = contract_types
        if after:
            params["after"] = after

        r = session.get(f"{DELTA_REST}/v2/products", params=params, timeout=10)
        data = r.json()
        if not data.get("success"):
            break

        page = data.get("result", [])
        results.extend(page)

        after = (data.get("meta") or {}).get("after")
        if not after:
            break

    # Keep only operational products (nice for a TV-like terminal)
    filtered = [p for p in results if p.get("state") == "live" and p.get("trading_status") == "operational"]
    return filtered


def fetch_history_candles(symbol_for_history: str, resolution: str, limit: int = 400) -> List[Dict[str, Any]]:
    """
    Seeds candles from /v2/history/candles (max 2000 in a response).
    Response format is list of {time, open, high, low, close, volume}.
    """
    # rough seconds per bar
    sec_map = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
        "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
        "1d": 86400, "1w": 604800
    }
    now = int(time.time())
    span = sec_map.get(resolution, 60) * limit
    start = now - span
    end = now

    params = {"resolution": resolution, "symbol": symbol_for_history, "start": start, "end": end}
    r = requests.get(f"{DELTA_REST}/v2/history/candles", params=params, timeout=10)
    data = r.json()
    if not data.get("success"):
        return []

    candles = data.get("result", []) or []

    # Normalize + sort
    out = []
    for c in candles:
        try:
            out.append(
                {
                    "time": int(c["time"]),
                    "open": float(c["open"]),
                    "high": float(c["high"]),
                    "low": float(c["low"]),
                    "close": float(c["close"]),
                    "volume": float(c.get("volume", 0) or 0),
                }
            )
        except Exception:
            continue

    out.sort(key=lambda x: x["time"])
    return out


# -----------------------------
# Real-time state + WS worker
# -----------------------------
@dataclass
class DeltaLiveState:
    lock: threading.Lock = field(default_factory=threading.Lock)

    status: str = "disconnected"
    last_msg_local_time: float = 0.0

    # chart candles
    candles: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=800))

    # ticker snapshot
    ticker: Dict[str, Any] = field(default_factory=dict)

    # orderbook
    orderbook: Dict[str, Any] = field(default_factory=dict)

    # trades
    trades: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=200))

    # errors
    last_error: Optional[str] = None


class DeltaWSWorker:
    def __init__(self, state: DeltaLiveState, product_symbol: str, resolution: str, candle_symbol: str):
        self.state = state
        self.product_symbol = product_symbol
        self.resolution = resolution
        self.candle_symbol = candle_symbol

        self._stop = threading.Event()
        self._ws: Optional[websocket.WebSocketApp] = None
        self._thread: Optional[threading.Thread] = None

    def start(self):
        def on_open(ws):
            with self.state.lock:
                self.state.status = "connected"
                self.state.last_error = None

            # Subscribe to: ticker, candles, l2 orderbook, all trades
            # Delta WS subscribe message format:
            payload = {
                "type": "subscribe",
                "payload": {
                    "channels": [
                        {"name": "v2/ticker", "symbols": [self.product_symbol]},
                        {"name": f"candlestick_{self.resolution}", "symbols": [self.candle_symbol]},
                        {"name": "l2_orderbook", "symbols": [self.product_symbol]},
                        {"name": "all_trades", "symbols": [self.product_symbol]},
                    ]
                },
            }
            ws.send(json.dumps(payload))

        def on_message(ws, message: str):
            try:
                msg = json.loads(message)
            except Exception:
                return

            now_local = time.time()

            with self.state.lock:
                self.state.last_msg_local_time = now_local

                msg_type = msg.get("type")

                # Candles
                if isinstance(msg_type, str) and msg_type.startswith("candlestick_"):
                    # candle_start_time is in microseconds in WS sample.
                    # We'll convert to seconds for lightweight-charts "time".
                    try:
                        t_sec = int(int(msg["candle_start_time"]) // 1_000_000)
                        candle = {
                            "time": t_sec,
                            "open": float(msg["open"]),
                            "high": float(msg["high"]),
                            "low": float(msg["low"]),
                            "close": float(msg["close"]),
                            "volume": float(msg.get("volume", 0) or 0),
                        }

                        if self.state.candles and self.state.candles[-1]["time"] == t_sec:
                            self.state.candles[-1] = candle
                        else:
                            self.state.candles.append(candle)
                    except Exception:
                        pass
                    return

                # L2 orderbook (full snapshot at interval)
                if msg_type == "l2_orderbook" and msg.get("symbol") == self.product_symbol:
                    # msg has "buy" and "sell" arrays of levels.
                    self.state.orderbook = msg
                    return

                # Trades snapshot + live trades
                if msg_type == "all_trades_snapshot" and msg.get("symbol") == self.product_symbol:
                    trades = msg.get("trades", []) or []
                    # Snapshot is last 50 trades. We'll append in time order.
                    for t in trades:
                        self._push_trade_locked(t)
                    return

                if msg_type == "all_trades" and msg.get("symbol") == self.product_symbol:
                    self._push_trade_locked(msg)
                    return

                # Ticker: docs show fields like open/close/high/low/mark_price/quotes/etc.
                # Some feeds include msg["type"]; some may not. We'll detect by presence.
                if msg.get("symbol") == self.product_symbol and ("mark_price" in msg or "quotes" in msg):
                    self.state.ticker = msg
                    return

        def on_error(ws, error):
            with self.state.lock:
                self.state.last_error = str(error)
                self.state.status = "error"

        def on_close(ws, close_status_code, close_msg):
            with self.state.lock:
                self.state.status = "disconnected"

        self._ws = websocket.WebSocketApp(
            DELTA_WS,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        def run():
            # ping_interval keeps socket active
            # (Delta disconnects idle sockets; pings help)
            while not self._stop.is_set():
                try:
                    self._ws.run_forever(ping_interval=20, ping_timeout=10)
                except Exception as e:
                    with self.state.lock:
                        self.state.last_error = str(e)
                        self.state.status = "error"
                # small backoff before reconnect
                time.sleep(2)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass

    def _push_trade_locked(self, t: Dict[str, Any]):
        """
        Adds a trade into state.trades.
        Delta trade has buyer_role/seller_role and timestamp in microseconds.
        We label 'aggressor' as:
          - BUY if buyer_role == 'taker'
          - SELL if seller_role == 'taker'
        """
        try:
            ts_us = int(t["timestamp"])
            ts_sec = ts_us // 1_000_000
            price = float(t["price"])
            size = float(t["size"])

            side = "?"
            if t.get("buyer_role") == "taker":
                side = "BUY"
            elif t.get("seller_role") == "taker":
                side = "SELL"

            self.state.trades.appendleft(
                {
                    "time": ts_sec,
                    "price": price,
                    "size": size,
                    "side": side,
                }
            )
        except Exception:
            return


# -----------------------------
# Session init
# -----------------------------
if "live_state" not in st.session_state:
    st.session_state.live_state = DeltaLiveState()

if "ws_worker" not in st.session_state:
    st.session_state.ws_worker = None

if "ws_key" not in st.session_state:
    st.session_state.ws_key = ""


# -----------------------------
# Top toolbar (TV-mobile-ish)
# -----------------------------
left, mid, right = st.columns([5, 3, 4])

with left:
    contract_type = st.selectbox(
        "Contract type",
        options=["perpetual_futures", "futures", "call_options", "put_options", "all"],
        index=0,
        label_visibility="collapsed",
    )

with mid:
    resolution = st.selectbox("TF", options=RESOLUTIONS, index=0, label_visibility="collapsed")

with right:
    price_source = st.selectbox("Price", options=["Traded", "Mark"], index=0, label_visibility="collapsed")


# Build the symbol universe from Delta public products list
products = fetch_all_live_products(contract_types=contract_type)
product_map = {p["symbol"]: p for p in products}

# Search box (important when options list is huge)
query = st.text_input("Search symbol", value="BTC", label_visibility="collapsed")
symbols = sorted(product_map.keys())
filtered = [s for s in symbols if query.upper() in s.upper()]
symbol = st.selectbox("Symbol", options=(filtered if filtered else symbols), index=0)

# Candle symbol rules:
# - Traded candles use product_symbol
# - Mark candles use "MARK:product_symbol" (WS candlesticks + REST history supports MARK:... symbols)
candle_symbol = f"MARK:{symbol}" if price_source == "Mark" else symbol
history_symbol = candle_symbol  # REST /history/candles uses MARK:${symbol} for mark candles


# -----------------------------
# Start / restart WS worker if selection changed
# -----------------------------
new_key = f"{symbol}|{resolution}|{price_source}"
if st.session_state.ws_key != new_key:
    # stop old worker
    if st.session_state.ws_worker is not None:
        st.session_state.ws_worker.stop()
        st.session_state.ws_worker = None

    # reset live state
    st.session_state.live_state = DeltaLiveState()

    # seed candles from REST history
    seed = fetch_history_candles(history_symbol, resolution, limit=400)
    with st.session_state.live_state.lock:
        for c in seed:
            st.session_state.live_state.candles.append(c)

    # start worker
    worker = DeltaWSWorker(
        state=st.session_state.live_state,
        product_symbol=symbol,
        resolution=resolution,
        candle_symbol=candle_symbol,
    )
    worker.start()
    st.session_state.ws_worker = worker
    st.session_state.ws_key = new_key


# Auto-refresh UI (does NOT reconnect; just redraws latest state)
st_autorefresh(interval=1000, key="ui_refresh")


# -----------------------------
# Header row: price + actions
# -----------------------------
h1, h2, h3, h4 = st.columns([4, 2, 2, 2])

with st.session_state.live_state.lock:
    ticker = dict(st.session_state.live_state.ticker)
    status = st.session_state.live_state.status
    last_err = st.session_state.live_state.last_error

mark_price = ticker.get("mark_price")
best_bid = ((ticker.get("quotes") or {}).get("best_bid") if isinstance(ticker.get("quotes"), dict) else None)
best_ask = ((ticker.get("quotes") or {}).get("best_ask") if isinstance(ticker.get("quotes"), dict) else None)

with h1:
    st.markdown(
        f"""
<div style="font-size:18px; font-weight:700; color:#d1d4dc;">
  {symbol} <span style="font-weight:400; color:#8b93a7;">({contract_type})</span>
</div>
<div style="font-size:13px; color:#8b93a7;">{price_source} candles • {resolution}</div>
""",
        unsafe_allow_html=True,
    )

with h2:
    st.markdown(
        f"<div style='text-align:right; color:#d1d4dc; font-size:22px; font-weight:700;'>{mark_price if mark_price is not None else '—'}</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='text-align:right; color:#8b93a7; font-size:12px;'>bid {best_bid or '—'} • ask {best_ask or '—'}</div>",
        unsafe_allow_html=True,
    )

with h3:
    st.button("SELL", use_container_width=True)

with h4:
    st.button("BUY", use_container_width=True)


# -----------------------------
# Main chart (Lightweight Charts)
# -----------------------------
with st.session_state.live_state.lock:
    candles_list = list(st.session_state.live_state.candles)

if not candles_list:
    st.info("Waiting for candles… (seed + live WS updates)")
else:
    # optional volume histogram
    volume_hist = []
    for c in candles_list:
        v = float(c.get("volume", 0) or 0)
        color = "rgba(8,153,129,0.6)" if c["close"] >= c["open"] else "rgba(242,54,69,0.6)"
        volume_hist.append({"time": c["time"], "value": v, "color": color})

    chartOptions = {
        "layout": {
            "background": {"type": "solid", "color": "#131722"},
            "textColor": "#d1d4dc",
        },
        "grid": {
            "vertLines": {"color": "#1e222d"},
            "horzLines": {"color": "#1e222d"},
        },
        "watermark": {
            "visible": True,
            "fontSize": 26,
            "horzAlign": "center",
            "vertAlign": "center",
            "color": "rgba(255, 255, 255, 0.07)",
            "text": f"{symbol} • {resolution}",
        },
        "timeScale": {"timeVisible": True, "secondsVisible": False},
        "rightPriceScale": {"borderColor": "#363c4e"},
        "crosshair": {"mode": 1},
    }

    series = [
        {
            "type": "Candlestick",
            "data": candles_list,
            "options": {
                "upColor": "#089981",
                "downColor": "#f23645",
                "borderVisible": False,
                "wickUpColor": "#089981",
                "wickDownColor": "#f23645",
            },
        },
        {
            "type": "Histogram",
            "data": volume_hist,
            "options": {
                "priceFormat": {"type": "volume"},
                "priceScaleId": "",  # separate
                "scaleMargins": {"top": 0.8, "bottom": 0.0},
            },
        },
    ]

    renderLightweightCharts([{"chart": chartOptions, "series": series}], key="delta_tv_chart")


# -----------------------------
# Bottom panels: Orderbook + Trades + Details (TV-ish tabs)
# -----------------------------
tab1, tab2, tab3 = st.tabs(["Orderbook", "Trades", "Instrument"])

with tab1:
    with st.session_state.live_state.lock:
        ob = dict(st.session_state.live_state.orderbook)

    if not ob:
        st.info("Waiting for L2 orderbook…")
    else:
        buy = ob.get("buy") or []
        sell = ob.get("sell") or []

        # show top N
        N = 15
        bids = pd.DataFrame(buy[:N])
        asks = pd.DataFrame(sell[:N])

        # normalize types
        for df in (bids, asks):
            if not df.empty:
                if "limit_price" in df.columns:
                    df["limit_price"] = df["limit_price"].astype(float)
                if "size" in df.columns:
                    df["size"] = df["size"].astype(float)

        c1, c2 = st.columns(2)
        with c1:
            st.caption("Bids (top)")
            st.dataframe(bids[["limit_price", "size"]] if not bids.empty else bids, use_container_width=True, height=380)
        with c2:
            st.caption("Asks (top)")
            st.dataframe(asks[["limit_price", "size"]] if not asks.empty else asks, use_container_width=True, height=380)

with tab2:
    with st.session_state.live_state.lock:
        trades = list(st.session_state.live_state.trades)

    if not trades:
        st.info("Waiting for trades… (snapshot of last 50, then live)")
    else:
        df = pd.DataFrame(trades)
        # human time
        df["ts"] = pd.to_datetime(df["time"], unit="s").dt.strftime("%H:%M:%S")
        df = df[["ts", "side", "price", "size"]]
        st.dataframe(df, use_container_width=True, height=420)

with tab3:
    p = product_map.get(symbol) or {}
    # Keep this simple but useful (TV-like "contract details")
    cols = ["symbol", "description", "contract_type", "tick_size", "contract_value", "state", "trading_status"]
    details = {k: p.get(k) for k in cols}
    st.json(details)


# -----------------------------
# Footer: connection status
# -----------------------------
with st.session_state.live_state.lock:
    last_msg = st.session_state.live_state.last_msg_local_time

age = (time.time() - last_msg) if last_msg else None
age_txt = f"{age:.1f}s ago" if age is not None else "—"

st.caption(f"WS status: {status} • last message: {age_txt}" + (f" • error: {last_err}" if last_err else ""))
