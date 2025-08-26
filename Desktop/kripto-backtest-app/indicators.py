
import pandas_ta as ta
import pandas as pd

def generate_all_indicators(
        df,
        # --- YENİ EKLENEN SATIRLAR ---
        ma_fast_period=20,  # Hızlı MA için varsayılan
        ma_slow_period=50,  # Yavaş MA için varsayılan
        # --- EKLENECEK KISIM SONU ---
        sma=50, # Bu satır artık grafik çizimi için kullanılacak
        ema=20, # Bu satır artık grafik çizimi için kullanılacak
        bb_period=20,
        bb_std=2.0,
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        macd_signal=9,
        adx_period=14,
        stoch_k_period=14,
        stoch_d_period=3,
        **kwargs
):
    """
    Tüm teknik göstergeleri hesaplar ve DataFrame'e ekler.
    """
    df_copy = df.copy()

    # --- YENİ: MA Kesişimi için Hızlı ve Yavaş Ortalamalar ---
    df_copy['SMA_fast'] = ta.sma(df_copy['Close'], length=ma_fast_period)
    df_copy['SMA_slow'] = ta.sma(df_copy['Close'], length=ma_slow_period)
    # --- EKLENECEK KISIM SONU ---

    # Grafikleme için tekil SMA ve EMA (Mevcut yapı korunuyor)
    df_copy['SMA'] = ta.sma(df_copy['Close'], length=sma)
    df_copy['EMA'] = ta.ema(df_copy['Close'], length=ema)

    # Bollinger Bantları
    bbands = ta.bbands(df_copy['Close'], length=bb_period, std=bb_std)
    if bbands is not None and not bbands.empty and len(bbands.columns) >= 3:
        df_copy['bb_lband'] = bbands.iloc[:, 0]
        df_copy['bb_mband'] = bbands.iloc[:, 1]
        df_copy['bb_hband'] = bbands.iloc[:, 2]

    # Diğer göstergeler (değişiklik yok)
    df_copy['RSI'] = ta.rsi(df_copy['Close'], length=rsi_period)
    macd = ta.macd(df_copy['Close'], fast=macd_fast, slow=macd_slow, signal=macd_signal)
    if macd is not None and not macd.empty:
        macd_col = next((col for col in macd.columns if col.startswith('MACD_')), None)
        macds_col = next((col for col in macd.columns if col.startswith('MACDs_')), None)
        if macd_col: df_copy['MACD'] = macd[macd_col]
        if macds_col: df_copy['MACD_signal'] = macd[macds_col]

    adx = ta.adx(df_copy['High'], df_copy['Low'], df_copy['Close'], length=adx_period)
    if adx is not None and not adx.empty:
        adx_col = next((col for col in adx.columns if col.startswith('ADX_')), None)
        if adx_col: df_copy['ADX'] = adx[adx_col]

    stoch = ta.stoch(df_copy['High'], df_copy['Low'], df_copy['Close'], k=stoch_k_period, d=stoch_d_period)
    if stoch is not None and not stoch.empty:
        stoch_k_col = next((col for col in stoch.columns if col.startswith('STOCHk_')), None)
        stoch_d_col = next((col for col in stoch.columns if col.startswith('STOCHd_')), None)
        if stoch_k_col: df_copy['Stoch_k'] = stoch[stoch_k_col]
        if stoch_d_col: df_copy['Stoch_d'] = stoch[stoch_d_col]

    try:
        df_copy['VWAP'] = ta.vwap(df_copy['High'], df_copy['Low'], df_copy['Close'], df_copy['Volume'])
    except Exception:
        df_copy['VWAP'] = pd.NA

    df_copy['ATR'] = ta.atr(df_copy['High'], df_copy['Low'], df_copy['Close'], length=14)

    return df_copy