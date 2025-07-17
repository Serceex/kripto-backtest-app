import pandas as pd
import requests

def get_binance_klines(symbol="BTCUSDT", interval="1h", limit=1000):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    data = requests.get(url, params=params).json()

    df = pd.DataFrame(data, columns=[
        'time', 'Open', 'High', 'Low', 'Close', 'Volume',
        '_', '_', '_', '_', '_', '_'
    ])
    df['time'] = pd.to_datetime(df['time'], unit='ms')
    df.set_index('time', inplace=True)
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
