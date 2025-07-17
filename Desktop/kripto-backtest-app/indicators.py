import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, EMAIndicator, SMAIndicator, ADXIndicator
from ta.volatility import BollingerBands

def calculate_vwap(df):
    try:
        q = df['Volume']
        p = df['Close']
        return (p * q).cumsum() / q.cumsum()
    except KeyError:
        return pd.Series([None] * len(df))

def generate_all_indicators(df, sma_period=50, ema_period=20, bb_period=20, bb_std=2):
    df = df.copy()

    # Her gösterge ayrı ayrı try/except içinde
    try:
        df['RSI'] = RSIIndicator(close=df['Close']).rsi()
    except Exception:
        df['RSI'] = None

    try:
        macd = MACD(close=df['Close'])
        df['MACD'] = macd.macd()
        df['MACD_signal'] = macd.macd_signal()
    except Exception:
        df['MACD'] = df['MACD_signal'] = None

    try:
        adx = ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'])
        df['ADX'] = adx.adx()
    except Exception:
        df['ADX'] = None

    try:
        bb = BollingerBands(close=df['Close'], window=bb_period, window_dev=bb_std)
        df['bb_hband'] = bb.bollinger_hband()
        df['bb_lband'] = bb.bollinger_lband()
        df['bb_mavg'] = bb.bollinger_mavg()
    except Exception:
        df['bb_hband'] = df['bb_lband'] = df['bb_mavg'] = None

    try:
        df['SMA'] = SMAIndicator(close=df['Close'], window=sma_period).sma_indicator()
    except Exception:
        df['SMA'] = None

    try:
        df['EMA'] = EMAIndicator(close=df['Close'], window=ema_period).ema_indicator()
    except Exception:
        df['EMA'] = None

    try:
        stoch = StochasticOscillator(high=df['High'], low=df['Low'], close=df['Close'])
        df['Stoch_k'] = stoch.stoch()
        df['Stoch_d'] = stoch.stoch_signal()
    except Exception:
        df['Stoch_k'] = df['Stoch_d'] = None

    try:
        df['VWAP'] = calculate_vwap(df)
    except Exception:
        df['VWAP'] = None

    return df
