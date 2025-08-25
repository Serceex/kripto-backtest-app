# indicators.py (KeyError hatası giderilmiş, en stabil hali)

import pandas_ta as ta
import pandas as pd
from ta.momentum import RSIIndicator


def calculate_vwap(df):
    try:
        q = df['Volume']
        p = df['Close']
        return (p * q).cumsum() / q.cumsum()
    except KeyError:
        return pd.Series([pd.NA] * len(df))


def generate_all_indicators(
        df,
        sma,
        ema,
        bb_period,
        bb_std,
        rsi_period,
        macd_fast,
        macd_slow,
        macd_signal,
        adx_period,
        stoch_k_period=14,
        stoch_d_period=3,
        **kwargs
):
    """
    Tüm teknik göstergeleri hesaplar ve DataFrame'e ekler.
    """
    df_copy = df.copy()

    # SMA ve EMA
    df_copy['SMA'] = ta.sma(df_copy['Close'], length=sma)
    df_copy['EMA'] = ta.ema(df_copy['Close'], length=ema)

    # --- YENİ VE HATAYA DAYANIKLI BOLLINGER BANTLARI MANTIĞI ---
    bbands = ta.bbands(df_copy['Close'], length=bb_period, std=bb_std)
    if bbands is not None and not bbands.empty and len(bbands.columns) >= 3:
        # Sütun adlarını tahmin etmek yerine, sırasına göre ata.
        # Bu yöntem, kütüphanenin ondalık sayıları nasıl formatladığından etkilenmez.
        df_copy['bb_lband'] = bbands.iloc[:, 0]  # İlk sütun her zaman Lower Band'dır (BBL)
        df_copy['bb_mband'] = bbands.iloc[:, 1]  # İkinci sütun her zaman Middle Band'dır (BBM)
        df_copy['bb_hband'] = bbands.iloc[:, 2]  # Üçüncü sütun her zaman Upper Band'dır (BBU)
    # --- DÜZELTME SONU ---

    # RSI
    df_copy['RSI'] = ta.rsi(df_copy['Close'], length=rsi_period)

    # MACD
    macd = ta.macd(df_copy['Close'], fast=macd_fast, slow=macd_slow, signal=macd_signal)
    if macd is not None and not macd.empty:
        # MACD için de dinamik sütun adı bulma yöntemini kullanalım
        macd_col = next((col for col in macd.columns if col.startswith('MACD_')), None)
        macds_col = next((col for col in macd.columns if col.startswith('MACDs_')), None)
        macdh_col = next((col for col in macd.columns if col.startswith('MACDh_')), None)

        if macd_col: df_copy['MACD'] = macd[macd_col]
        if macds_col: df_copy['MACD_signal'] = macd[macds_col]
        if macdh_col: df_copy['MACD_hist'] = macd[macdh_col]

    # ADX
    adx = ta.adx(df_copy['High'], df_copy['Low'], df_copy['Close'], length=adx_period)
    if adx is not None and not adx.empty:
        adx_col = next((col for col in adx.columns if col.startswith('ADX_')), None)
        if adx_col: df_copy['ADX'] = adx[adx_col]

    # Stokastik
    stoch = ta.stoch(df_copy['High'], df_copy['Low'], df_copy['Close'])
    if stoch is not None and not stoch.empty:
        stoch_k_col = next((col for col in stoch.columns if col.startswith('STOCHk_')), None)
        stoch_d_col = next((col for col in stoch.columns if col.startswith('STOCHd_')), None)
        if stoch_k_col: df_copy['Stoch_k'] = stoch[stoch_k_col]
        if stoch_d_col: df_copy['Stoch_d'] = stoch[stoch_d_col]

    # VWAP
    try:
        df_copy['VWAP'] = ta.vwap(df_copy['High'], df_copy['Low'], df_copy['Close'], df_copy['Volume'])
    except Exception:
        df_copy['VWAP'] = pd.NA

    df_copy['ATR'] = ta.atr(df_copy['High'], df_copy['Low'], df_copy['Close'], length=14)

    # YENİ: Stokastik Hesaplaması
    stoch = ta.stoch(df_copy['High'], df_copy['Low'], df_copy['Close'], k=stoch_k_period, d=stoch_d_period)
    if stoch is not None and not stoch.empty:
        stoch_k_col = next((col for col in stoch.columns if col.startswith('STOCHk_')), None)
        stoch_d_col = next((col for col in stoch.columns if col.startswith('STOCHd_')), None)
        if stoch_k_col: df_copy['Stoch_k'] = stoch[stoch_k_col]
        if stoch_d_col: df_copy['Stoch_d'] = stoch[stoch_d_col]

    # YENİ: VWAP Hesaplaması (zaten vardı, ama burada olduğundan emin olun)
    try:
        df_copy['VWAP'] = ta.vwap(df_copy['High'], df_copy['Low'], df_copy['Close'], df_copy['Volume'])
    except Exception:
        df_copy['VWAP'] = pd.NA

    return df_copy
