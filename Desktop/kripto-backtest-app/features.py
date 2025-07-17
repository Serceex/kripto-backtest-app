import pandas as pd
import numpy as np

def prepare_features(df, forward_window=5, threshold=0.5):
    """
    Feature engineering & target creation for ML.

    Args:
        df: DataFrame with technical indicators and OHLCV.
        forward_window: lookahead bars for return calculation.
        threshold: return threshold (%) to define buy/sell/hold.

    Returns:
        X: features dataframe (aligned)
        y: target series (+1 buy, -1 sell, 0 hold)
        df: original df with target column
    """
    df = df.copy()

    # Calculate future returns
    df['future_close'] = df['Close'].shift(-forward_window)
    df['return_future'] = (df['future_close'] - df['Close']) / df['Close'] * 100

    # Target labeling
    conditions = [
        df['return_future'] > threshold,
        df['return_future'] < -threshold
    ]
    choices = [2, 0]  # Sat = 0, Bekle = 1, Al = 2 olarak yeniden etiketle
    df['target'] = 1  # default bekle
    df.loc[conditions[0], 'target'] = 2  # Al
    df.loc[conditions[1], 'target'] = 0  # Sat

    # Drop rows with NaN target due to shifting
    df = df.dropna(subset=['target'])

    # Select features (all numeric except target columns)
    feature_cols = [
        'Open', 'High', 'Low', 'Close', 'Volume',
        'RSI', 'MACD', 'MACD_signal', 'ADX',
        'bb_hband', 'bb_lband', 'bb_mavg',
        'SMA', 'EMA',
        'Stoch_k', 'Stoch_d',
        'VWAP'
    ]

    # Keep only columns present in df
    feature_cols = [c for c in feature_cols if c in df.columns]

    X = df[feature_cols]
    y = df['target']

    return X, y, df
