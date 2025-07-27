import numpy as np
import pandas as pd


def generate_signals(df,
                     use_rsi=True,
                     rsi_buy=30,
                     rsi_sell=70,
                     use_macd=True,
                     macd_fast=12,
                     macd_slow=26,
                     macd_signal=9,
                     use_bb=True,
                     use_adx=True,
                     adx_threshold=25,
                     signal_mode='or',
                     signal_direction='Both',
                     use_puzzle_bot=False):
    df = df.copy()

    # Eksik kolonları doldur
    required_cols = ['RSI', 'MACD', 'MACD_signal', 'bb_lband', 'bb_hband', 'ADX']
    for col in required_cols:
        if col not in df.columns:
            df[col] = np.nan

    # Şart listeleri
    buy_conditions = []
    sell_conditions = []

    # Long (Al) sinyali şartları
    if use_rsi:
        buy_conditions.append(df['RSI'] < rsi_buy)
    if use_macd:
        buy_conditions.append(df['MACD'] > df['MACD_signal'])
    if use_bb:
        buy_conditions.append(df['Close'] < df['bb_lband'])
    if use_adx:
        buy_conditions.append(df['ADX'] > adx_threshold)

    # Short (Sat) sinyali şartları
    if use_rsi:
        sell_conditions.append(df['RSI'] > rsi_sell)
    if use_macd:
        sell_conditions.append(df['MACD'] < df['MACD_signal'])
    if use_bb:
        sell_conditions.append(df['Close'] > df['bb_hband'])
    if use_adx:
        sell_conditions.append(df['ADX'] > adx_threshold)

    # Koşulları birleştirme fonksiyonu
    def combine_conditions(conditions):
        if not conditions:
            return pd.Series([False] * len(df), index=df.index)
        if signal_mode == 'and':
            return pd.concat(conditions, axis=1).all(axis=1)
        else:
            return pd.concat(conditions, axis=1).any(axis=1)

    # Al ve Sat sinyalleri üret
    df['Buy_Signal'] = combine_conditions(buy_conditions)
    df['Sell_Signal'] = combine_conditions(sell_conditions)

    # Ana Signal kolonu üretimi
    df['Signal'] = 'Bekle'
    if signal_direction == 'Long':
        df.loc[df['Buy_Signal'], 'Signal'] = 'Al'
        df.loc[df['Sell_Signal'], 'Signal'] = 'Sat'  # Long pozisyon kapama
    elif signal_direction == 'Short':
        df.loc[df['Sell_Signal'], 'Signal'] = 'Sat'
        df.loc[df['Buy_Signal'], 'Signal'] = 'Al'  # Short kapama
    else:  # Both
        df.loc[df['Buy_Signal'], 'Signal'] = 'Al'
        df.loc[df['Sell_Signal'], 'Signal'] = 'Sat'

    # Güvenlik: Signal kolonu numeric değilse sayısal karşılığı da üret (opsiyonel)
    df['Signal_Value'] = df['Signal'].map({'Al': 1, 'Sat': -1, 'Bekle': 0})

    # Uyarı: Hiçbir sinyal oluşmamışsa bilgilendirme
    if (df['Signal'] == 'Bekle').all():
        print("⚠️ Hiçbir sinyal üretilmedi. Seçilen göstergelerden hiçbiri tetiklenmedi.")

    # Sinyal istatistikleri
    print(f"📈 Al sinyali sayısı: {df['Buy_Signal'].sum()}")
    print(f"📉 Sat sinyali sayısı: {df['Sell_Signal'].sum()}")

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

        if position is None:
            if signal == 'Al':
                position = 'Long'
                entry_price = price
                entry_time = time_idx
            elif signal == 'Sat':
                position = 'Short'
                entry_price = price
                entry_time = time_idx

        elif position == 'Long':
            if signal == 'Sat':
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

        elif position == 'Short':
            if signal == 'Al':
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

    # Pozisyon açık kalırsa son kaydı ekle
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


def create_signal_column(df):
    df['Signal'] = 'Bekle'
    df.loc[df['Buy_Signal'] == True, 'Signal'] = 'Al'
    df.loc[df['Sell_Signal'] == True, 'Signal'] = 'Sat'
    return df


