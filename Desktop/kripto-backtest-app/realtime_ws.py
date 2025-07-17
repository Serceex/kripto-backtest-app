# realtime_ws.py

import websocket
import json
import pandas as pd
from datetime import datetime
from indicators import generate_all_indicators
from signals import generate_signals

# Küresel veri çerçevesi
ohlcv_data = []

def on_message(ws, message):
    global ohlcv_data
    data = json.loads(message)['k']

    if data['x']:  # x=True ise kline kapanmıştır
        ohlcv_data.append({
            "time": datetime.fromtimestamp(data['t'] / 1000),
            "Open": float(data['o']),
            "High": float(data['h']),
            "Low": float(data['l']),
            "Close": float(data['c']),
            "Volume": float(data['v']),
        })

        df = pd.DataFrame(ohlcv_data)
        df.set_index("time", inplace=True)

        # Göstergeleri hesapla
        df = generate_all_indicators(df)
        df = generate_signals(df,
                              use_rsi=True, rsi_buy=30, rsi_sell=70,
                              use_macd=True, use_bbands=True, use_adx=True, adx_threshold=25,
                              signal_mode="Long Only")

        last_signal = df['Signal'].iloc[-1]
        last_close = df['Close'].iloc[-1]

        print(f"📈 Fiyat: {last_close:.2f} | Sinyal: {last_signal}")

        # Son 100 bar ile sınırlı tut
        if len(ohlcv_data) > 100:
            ohlcv_data = ohlcv_data[-100:]

def on_error(ws, error):
    print(f"[HATA] {error}")

def on_close(ws, close_status_code, close_msg):
    print("🔌 Bağlantı kapandı.")

def on_open(ws):
    print("🟢 Binance WebSocket'e bağlanıldı.")

def start_realtime(symbol="btcusdt", interval="1m"):
    stream_url = f"wss://stream.binance.com:9443/ws/{symbol}@kline_{interval}"
    ws = websocket.WebSocketApp(stream_url,
                                on_message=on_message,
                                on_error=on_error,
                                on_close=on_close,
                                on_open=on_open)
    ws.run_forever()
