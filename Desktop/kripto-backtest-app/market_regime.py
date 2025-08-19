# market_regime.py

import pandas as pd
import pandas_ta as ta

# Projemizin kendi modüllerini import ediyoruz
from utils import get_fear_and_greed_index, get_binance_klines


def analyze_volatility(df: pd.DataFrame):
    """
    Piyasadaki volatiliteyi Bollinger Bant Genişliği (BBW) kullanarak analiz eder.
    BBW = (Üst Bant - Alt Bant) / Orta Bant
    """
    bbands = ta.bbands(df['Close'], length=20, std=2)
    bbw = (bbands['BBU_20_2.0'] - bbands['BBL_20_2.0']) / bbands['BBM_20_2.0']

    # Son 100 periyottaki BBW değerlerine göre eşik belirleyelim
    low_threshold = bbw.rolling(window=100).quantile(0.25).iloc[-1]
    high_threshold = bbw.rolling(window=100).quantile(0.75).iloc[-1]

    current_bbw = bbw.iloc[-1]

    if current_bbw < low_threshold:
        return "DÜŞÜK VOLATİLİTE"
    elif current_bbw > high_threshold:
        return "YÜKSEK VOLATİLİTE"
    else:
        return "NORMAL VOLATİLİTE"


def analyze_trend(df: pd.DataFrame):
    """
    Piyasadaki trendin gücünü ADX (Average Directional Index) kullanarak analiz eder.
    """
    adx = ta.adx(df['High'], df['Low'], df['Close'], length=14)
    current_adx = adx[f'ADX_14'].iloc[-1]

    if current_adx < 20:
        return "TRENDSİZ PİYASA"
    elif current_adx < 30:
        return "GÜÇLENEN TREND"
    else:
        return "GÜÇLÜ TREND"


def analyze_sentiment():
    """
    Piyasa duyarlılığını Korku ve Hırs Endeksi ile analiz eder.
    """
    fng_data = get_fear_and_greed_index()
    if not fng_data:
        return "BİLİNMİYOR"

    value = fng_data['value']
    if value < 25:
        return "AŞIRI KORKU"
    elif value < 45:
        return "KORKU"
    elif value > 75:
        return "AŞIRI AÇGÖZLÜLÜK"
    elif value > 55:
        return "AÇGÖZLÜLÜK"
    else:
        return "NÖTR"


def get_market_regime(symbol="BTCUSDT", interval="4h"):
    """
    Tüm analizleri birleştirerek mevcut piyasa rejimini belirler.
    Orkestratör bu fonksiyonu kullanacak.
    """
    print("--- 🤖 ORKESTRATÖR: Piyasa rejimi analizi başlatıldı... ---")

    # Genel piyasa durumu için referans veri setini çek
    df_market = get_binance_klines(symbol=symbol, interval=interval, limit=200)

    if df_market.empty:
        print("HATA: Orkestratör için piyasa verisi alınamadı.")
        return None

    regime = {
        "volatility": analyze_volatility(df_market),
        "trend_strength": analyze_trend(df_market),
        "sentiment": analyze_sentiment()
    }

    print(f"--- 🤖 ORKESTRATÖR: Mevcut Rejim Tespiti -> {regime} ---")
    return regime


if __name__ == '__main__':
    # Bu dosyayı doğrudan çalıştırarak piyasa analizini test edebilirsiniz
    current_regime = get_market_regime()
    if current_regime:
        print("\n--- PİYASA REJİM ANALİZ SONUCU ---")
        for key, value in current_regime.items():
            print(f"- {key.capitalize()}: {value}")