import pandas as pd
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import MACD, EMAIndicator, SMAIndicator, ADXIndicator
from ta.volatility import BollingerBands

def calculate_vwap(df):
    q = df['Volume']
    p = df['Close']
    return (p * q).cumsum() / q.cumsum()

def generate_all_indicators(df, sma_period=50, ema_period=20, bb_period=20, bb_std=2):
    df = df.copy()

    # Yetersiz veri kontrolü (ADX için min 15-20 bar gerekir)
    if len(df) < 20:
        return df

    # RSI
    df['RSI'] = RSIIndicator(close=df['Close']).rsi()

    # MACD
    macd = MACD(close=df['Close'])
    df['MACD'] = macd.macd()
    df['MACD_signal'] = macd.macd_signal()

    # ADX (yeterli veri kontrolü ile)
    try:
        adx = ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'])
        df['ADX'] = adx.adx()
    except Exception:
        df['ADX'] = None

    # Bollinger Bands
    bb = BollingerBands(close=df['Close'], window=bb_period, window_dev=bb_std)
    df['bb_hband'] = bb.bollinger_hband()
    df['bb_lband'] = bb.bollinger_lband()
    df['bb_mavg'] = bb.bollinger_mavg()

    # SMA & EMA
    df['SMA'] = SMAIndicator(close=df['Close'], window=sma_period).sma_indicator()
    df['EMA'] = EMAIndicator(close=df['Close'], window=ema_period).ema_indicator()

    # Stochastic Oscillator
    stoch = StochasticOscillator(high=df['High'], low=df['Low'], close=df['Close'])
    df['Stoch_k'] = stoch.stoch()
    df['Stoch_d'] = stoch.stoch_signal()

    # VWAP
    df['VWAP'] = calculate_vwap(df)

    return df

