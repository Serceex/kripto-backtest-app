import numpy as np
import pandas as pd
from telegram_alert import send_telegram_message

def generate_signals(df, use_rsi, rsi_buy, rsi_sell,
                     use_macd, use_bbands,
                     use_adx, adx_threshold,
                     signal_mode="Long Only",
                     use_puzzle_bot=False):
    df = df.copy()
    df['Signal'] = 'Bekle'

    conditions_buy = []
    conditions_sell = []

    if use_rsi:
        conditions_buy.append(df['RSI'] < rsi_buy)
        conditions_sell.append(df['RSI'] > rsi_sell)

    if use_macd:
        conditions_buy.append(df['MACD'] > df['MACD_signal'])
        conditions_sell.append(df['MACD'] < df['MACD_signal'])

    if use_bbands:
        conditions_buy.append(df['Close'] <= df['bb_lband'])
        conditions_sell.append(df['Close'] >= df['bb_hband'])

    if use_adx:
        conditions_buy.append(df['ADX'] > adx_threshold)
        conditions_sell.append(df['ADX'] > adx_threshold)

    buy_cond = np.logical_and.reduce(conditions_buy) if conditions_buy else np.array([False]*len(df))
    sell_cond = np.logical_and.reduce(conditions_sell) if conditions_sell else np.array([False]*len(df))

    # Puzzle Strateji Botu Basit Örneği: MACD ve RSI'nın kesişiminden ekstra al/sat sinyali
    if use_puzzle_bot:
        puzzle_buy = (df['MACD'] > df['MACD_signal']) & (df['RSI'] < rsi_buy)
        puzzle_sell = (df['MACD'] < df['MACD_signal']) & (df['RSI'] > rsi_sell)
        buy_cond = buy_cond | puzzle_buy
        sell_cond = sell_cond | puzzle_sell

    if signal_mode == "Long Only":
        df.loc[buy_cond, 'Signal'] = 'Al'
        df.loc[sell_cond, 'Signal'] = 'Sat'
    elif signal_mode == "Long & Short":
        df.loc[buy_cond, 'Signal'] = 'Al'
        df.loc[sell_cond, 'Signal'] = 'Short'

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
