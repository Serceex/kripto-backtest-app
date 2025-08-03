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
        sma,  # 'sma_period' yerine 'sma' olarak güncellendi
        ema,  # 'ema_period' yerine 'ema' olarak güncellendi
        bb_period,
        bb_std,
        rsi_period,
        macd_fast,
        macd_slow,
        macd_signal,
        adx_period,
        **kwargs  # Beklenmeyen diğer tüm argümanları yakalamak için eklendi
):
    """
    Tüm teknik göstergeleri hesaplar ve DataFrame'e ekler.
    Fonksiyon imzası, app.py'daki strategy_params sözlüğü ile uyumlu hale getirildi.
    """
    df_copy = df.copy()

    # Artık parametre olarak geldiği için fonksiyon içindeki sabit tanımlamalar kaldırıldı.

    # SMA ve EMA
    df_copy['SMA'] = ta.sma(df_copy['Close'], length=sma)  # Değişken adı güncellendi
    df_copy['EMA'] = ta.ema(df_copy['Close'], length=ema)  # Değişken adı güncellendi

    # Bollinger Bantları
    bbands = ta.bbands(df_copy['Close'], length=bb_period, std=bb_std)
    if bbands is not None and not bbands.empty:
        df_copy['bb_lband'] = bbands[f'BBL_{bb_period}_{bb_std:.1f}']
        df_copy['bb_mband'] = bbands[f'BBM_{bb_period}_{bb_std:.1f}']
        df_copy['bb_hband'] = bbands[f'BBU_{bb_period}_{bb_std:.1f}']

    # RSI
    df_copy['RSI'] = ta.rsi(df_copy['Close'], length=rsi_period)

    # MACD
    macd = ta.macd(df_copy['Close'], fast=macd_fast, slow=macd_slow, signal=macd_signal)
    if macd is not None and not macd.empty:
        df_copy['MACD'] = macd[f'MACD_{macd_fast}_{macd_slow}_{macd_signal}']
        df_copy['MACD_signal'] = macd[f'MACDs_{macd_fast}_{macd_slow}_{macd_signal}']
        df_copy['MACD_hist'] = macd[f'MACDh_{macd_fast}_{macd_slow}_{macd_signal}']

    # ADX
    adx = ta.adx(df_copy['High'], df_copy['Low'], df_copy['Close'], length=adx_period)
    if adx is not None and not adx.empty:
        df_copy['ADX'] = adx[f'ADX_{adx_period}']
        df_copy['DMP'] = adx[f'DMP_{adx_period}']
        df_copy['DMN'] = adx[f'DMN_{adx_period}']

    # Stokastik
    stoch = ta.stoch(df_copy['High'], df_copy['Low'], df_copy['Close'])
    if stoch is not None and not stoch.empty:
        df_copy['Stoch_k'] = stoch['STOCHk_14_3_3']
        df_copy['Stoch_d'] = stoch['STOCHd_14_3_3']

    # VWAP
    try:
        df_copy['VWAP'] = ta.vwap(df_copy['High'], df_copy['Low'], df_copy['Close'], df_copy['Volume'])
    except Exception:
        df_copy['VWAP'] = pd.NA

    return df_copy