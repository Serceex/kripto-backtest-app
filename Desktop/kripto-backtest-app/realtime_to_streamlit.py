# realtime_to_streamlit.py
import websocket
import json
import pandas as pd
from datetime import datetime
from indicators import generate_all_indicators
from signals import generate_signals

def websocket_runner(shared_data, symbol="btcusdt", interval="1m"):
    ohlcv_data = []

    def on_message(ws, message):
        nonlocal ohlcv_data
        data = json.loads(message)['k']
        if data['x']:  # Bar kapanmış
            ohlcv_data.append({
                "time": datetime.fromtimestamp(data['t'] / 1000),
                "Open": float(data['o']),
                "High": float(data['h']),
                "Low": float(data['l']),
                "Close": float(data['c']),
                "Volume": float(data['v']),
            })

            # Sadece son 100 barı sakla
            if len(ohlcv_data) > 150:
                ohlcv_data = ohlcv_data[-100:]

            shared_data["ohlcv"] = ohlcv_data

    def on_error(ws, error): print("WebSocket HATA:", error)
    def on_close(ws, *args): print("WebSocket KAPANDI.")
    def on_open(ws): print("WebSocket BAĞLANDI.")

    ws = websocket.WebSocketApp(
        f"wss://stream.binance.com:9443/ws/{symbol}@kline_{interval}",
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open
    )
    ws.run_forever()

