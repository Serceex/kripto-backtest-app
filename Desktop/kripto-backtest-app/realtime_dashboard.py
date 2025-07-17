import streamlit as st
import pandas as pd
import time
from multiprocessing import Process, Manager
from realtime_to_streamlit import websocket_runner
from indicators import generate_all_indicators
from signals import generate_signals
import plotly.graph_objects as go

st.set_page_config(layout="wide")
st.title("📈 Canlı Kripto Grafiği")

symbol = st.selectbox("Sembol", ["btcusdt", "ethusdt", "solusdt"])
interval = st.selectbox("Zaman Dilimi", ["1m", "5m", "15m"])
start = st.button("🚀 Başlat")

if start:
    manager = Manager()
    shared_data = manager.dict()
    p = Process(target=websocket_runner, args=(shared_data, symbol, interval))
    p.start()

    chart_placeholder = st.empty()

    try:
        while True:
            if "ohlcv" in shared_data:
                df = pd.DataFrame(shared_data["ohlcv"])
                df.set_index("time", inplace=True)
                df = generate_all_indicators(df)
                df = generate_signals(df,
                                      use_rsi=True, rsi_buy=30, rsi_sell=70,
                                      use_macd=True, use_bbands=True,
                                      use_adx=True, adx_threshold=25,
                                      signal_mode="Long Only")

                fig = go.Figure()

                # Candlestick
                fig.add_trace(go.Candlestick(
                    x=df.index,
                    open=df['Open'], high=df['High'],
                    low=df['Low'], close=df['Close'],
                    name="Fiyat"
                ))

                # Sinyaller
                buy_signals = df[df['Signal'] == 'Al']
                sell_signals = df[df['Signal'] == 'Sat']
                fig.add_trace(go.Scatter(
                    x=buy_signals.index,
                    y=buy_signals['Low'] * 0.995,
                    mode='markers',
                    marker=dict(color='green', size=10, symbol='arrow-up'),
                    name='Al'
                ))
                fig.add_trace(go.Scatter(
                    x=sell_signals.index,
                    y=sell_signals['High'] * 1.005,
                    mode='markers',
                    marker=dict(color='red', size=10, symbol='arrow-down'),
                    name='Sat'
                ))

                fig.update_layout(
                    xaxis_rangeslider_visible=False,
                    height=600,
                    showlegend=True,
                    title=f"{symbol.upper()} - Canlı Grafik"
                )

                chart_placeholder.plotly_chart(fig, use_container_width=True)

            time.sleep(3)
    except KeyboardInterrupt:
        p.terminate()
