import pandas_ta as ta
import pandas as pd
from ta.momentum import RSIIndicator


# Eğer ta.vwap ile sorun yaşarsanız ve kendiniz hesaplamak isterseniz bu fonksiyon kalabilir.
# Aksi takdirde, pandas_ta'nın VWAP'ını kullanacağımız için bu fonksiyona ihtiyacınız olmayabilir.
def calculate_vwap(df):
    try:
        q = df['Volume']
        p = df['Close']
        return (p * q).cumsum() / q.cumsum()
    except KeyError:
        # Volume sütunu yoksa veya hata olursa NaN ile doldur
        return pd.Series([pd.NA] * len(df)) # pd.NA kullanmak daha tutarlı

def generate_all_indicators(
    df,
    sma_period,
    ema_period,
    bb_period,
    bb_std,
    rsi_period,
    macd_fast,
    macd_slow,
    macd_signal,
    adx_period
):

    df_copy = df.copy()

    # MACD
    macd = ta.macd(df_copy['Close'], fast=macd_fast, slow=macd_slow, signal=macd_signal)
    df_copy['MACD'] = macd[f'MACD_{macd_fast}_{macd_slow}_{macd_signal}']
    df_copy['MACD_signal'] = macd[f'MACDs_{macd_fast}_{macd_slow}_{macd_signal}']
    df_copy['MACD_hist'] = macd[f'MACDh_{macd_fast}_{macd_slow}_{macd_signal}']


    # Sabit parametreler (kullanıcıdan alınmıyor)
    rsi_period = 14
    macd_fast = 12
    macd_slow = 26
    macd_signal = 9
    adx_period = 14

    # SMA ve EMA
    df_copy['SMA'] = ta.sma(df_copy['Close'], length=sma_period)
    df_copy['EMA'] = ta.ema(df_copy['Close'], length=ema_period)

    # Bollinger Bantları
    bbands = ta.bbands(df_copy['Close'], length=bb_period, std=bb_std)
    df_copy['bb_lband'] = bbands[f'BBL_{bb_period}_{bb_std}']
    df_copy['bb_mband'] = bbands[f'BBM_{bb_period}_{bb_std}']
    df_copy['bb_hband'] = bbands[f'BBU_{bb_period}_{bb_std}']

    # RSI
    df_copy['RSI'] = ta.rsi(df_copy['Close'], length=rsi_period)

    # MACD
    macd = ta.macd(df_copy['Close'], fast=macd_fast, slow=macd_slow, signal=macd_signal)
    df_copy['MACD'] = macd[f'MACD_{macd_fast}_{macd_slow}_{macd_signal}']
    df_copy['MACD_Signal'] = macd[f'MACDs_{macd_fast}_{macd_slow}_{macd_signal}']
    df_copy['MACD_Hist'] = macd[f'MACDh_{macd_fast}_{macd_slow}_{macd_signal}']

    # ADX
    adx = ta.adx(df_copy['High'], df_copy['Low'], df_copy['Close'], length=adx_period)
    df_copy['ADX'] = adx[f'ADX_{adx_period}']
    df_copy['DMP'] = adx[f'DMP_{adx_period}']
    df_copy['DMN'] = adx[f'DMN_{adx_period}']

    # Stokastik
    stoch = ta.stoch(df_copy['High'], df_copy['Low'], df_copy['Close'])
    df_copy['Stoch_k'] = stoch['STOCHk_14_3_3']
    df_copy['Stoch_d'] = stoch['STOCHd_14_3_3']

    # VWAP
    try:
        df_copy['VWAP'] = ta.vwap(df_copy['High'], df_copy['Low'], df_copy['Close'], df_copy['Volume'])
    except Exception:
        df_copy['VWAP'] = pd.NA

    return df_copy
