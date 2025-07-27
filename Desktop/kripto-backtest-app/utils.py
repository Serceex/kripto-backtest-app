from binance.client import Client
import pandas as pd
import streamlit as st

# API bilgilerini streamlit secrets'tan al
api_key = st.secrets["binance"]["api_key"]
api_secret = st.secrets["binance"]["api_secret"]

# Binance istemcisini oluştur
#client = Client(api_key, api_secret)
client = Client(api_key, api_secret, testnet=True)
client.API_URL = 'https://testnet.binance.vision/api'


def get_binance_klines(symbol="BTCUSDT", interval="1h", limit=1000):
    """Binance API üzerinden OHLCV verisi çeker"""
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)

    # DataFrame'e dönüştür
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
        'Close_time', 'Quote_asset_volume', 'Number_of_trades',
        'Taker_buy_base_asset_volume', 'Taker_buy_quote_asset_volume', 'Ignore'
    ])

    # Tip dönüşümleri ve timestamp düzenleme
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)

    return df

def calculate_fibonacci_levels(df):
    max_price = df['High'][-100:].max()
    min_price = df['Low'][-100:].min()
    diff = max_price - min_price
    levels = {
        '0%': max_price,
        '23.6%': max_price - 0.236 * diff,
        '38.2%': max_price - 0.382 * diff,
        '50%': max_price - 0.5 * diff,
        '61.8%': max_price - 0.618 * diff,
        '100%': min_price
    }
    return levels
