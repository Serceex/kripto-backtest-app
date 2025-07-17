import numpy as np
import pandas as pd
from telegram_alert import send_telegram_message


def generate_signals(df,
                     use_rsi=True,
                     use_macd=True,
                     use_bb=True,
                     use_adx=True,
                     use_puzzle_bot=True,
                     signal_mode='and'):
    df = df.copy()
    conditions_buy = []
    conditions_sell = []

    # Eksik kolonları güvenlik için ekle
    safe_columns = {
        'RSI': None, 'MACD': None, 'MACD_signal': None,
        'bb_lband': None, 'bb_hband': None,
        'ADX': None, 'Stoch_k': None, 'Stoch_d': None
    }
    for col in safe_columns:
        if col not in df.columns:
            df[col] = safe_columns[col]

    # RSI
    if use_rsi and 'RSI' in df.columns:
        conditions_buy.append(df['RSI'] < 30)
        conditions_sell.append(df['RSI'] > 70)

    # MACD
    if use_macd and 'MACD' in df.columns and 'MACD_signal' in df.columns:
        conditions_buy.append(df['MACD'] > df['MACD_signal'])
        conditions_sell.append(df['MACD'] < df['MACD_signal'])

    # Bollinger Bands
    if use_bb and 'bb_lband' in df.columns and 'bb_hband' in df.columns:
        conditions_buy.append(df['Close'] < df['bb_lband'])
        conditions_sell.append(df['Close'] > df['bb_hband'])

    # ADX
    if use_adx and 'ADX' in df.columns:
        conditions_buy.append(df['ADX'] > 25)
        conditions_sell.append(df['ADX'] < 20)

    # Puzzle Bot (örnek kurallar)
    if use_puzzle_bot and 'Stoch_k' in df.columns and 'Stoch_d' in df.columns:
        conditions_buy.append((df['Stoch_k'] < 20) & (df['Stoch_k'] > df['Stoch_d']))
        conditions_sell.append((df['Stoch_k'] > 80) & (df['Stoch_k'] < df['Stoch_d']))

    # Sinyal üretimi
    if conditions_buy:
        buy_df = pd.concat(conditions_buy, axis=1)
        sell_df = pd.concat(conditions_sell, axis=1)
        if signal_mode == 'and':
            df['Buy_Signal'] = buy_df.all(axis=1)
            df['Sell_Signal'] = sell_df.all(axis=1)
        else:
            df['Buy_Signal'] = buy_df.any(axis=1)
            df['Sell_Signal'] = sell_df.any(axis=1)
    else:
        # Eğer hiç koşul yoksa tümü False olsun
        df['Buy_Signal'] = False
        df['Sell_Signal'] = False

    return df



def backtest_signals(df):
    trades = []
    position = None
    entry_price = 0
    entry_time = None

    for i in range(len(df)):
        signal = df['Signal'].iloc[i]
        price = df['Close'].iloc[i]
        time_idx = df.index[i]

        if signal == 'Al' and position is None:
            position = 'Long'
            entry_price = price
            entry_time = time_idx
        elif signal == 'Sat' and position == 'Long':
            exit_price = price
            ret = (exit_price - entry_price) / entry_price * 100
            trades.append({
                'Pozisyon': 'Long',
                'Giriş Zamanı': entry_time,
                'Çıkış Zamanı': time_idx,
                'Giriş Fiyatı': entry_price,
                'Çıkış Fiyatı': exit_price,
                'Getiri (%)': round(ret, 2)
            })
            position = None
        elif signal == 'Short' and position is None:
            position = 'Short'
            entry_price = price
            entry_time = time_idx
        elif signal == 'Al' and position == 'Short':
            exit_price = price
            ret = (entry_price - exit_price) / entry_price * 100
            trades.append({
                'Pozisyon': 'Short',
                'Giriş Zamanı': entry_time,
                'Çıkış Zamanı': time_idx,
                'Giriş Fiyatı': entry_price,
                'Çıkış Fiyatı': exit_price,
                'Getiri (%)': round(ret, 2)
            })
            position = None

    # Eğer pozisyon açık kalmışsa son olarak ekle
    if position is not None:
        trades.append({
            'Pozisyon': position,
            'Giriş Zamanı': entry_time,
            'Çıkış Zamanı': pd.NaT,
            'Giriş Fiyatı': entry_price,
            'Çıkış Fiyatı': np.nan,
            'Getiri (%)': np.nan
        })

    return pd.DataFrame(trades)
