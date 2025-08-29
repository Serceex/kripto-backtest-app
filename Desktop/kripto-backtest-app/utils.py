# utils.py (Orijinal Hali)

import streamlit as st
from binance.client import Client
import pandas as pd
import numpy as np
import requests

try:
    api_key = st.secrets["binance"]["api_key"]
    api_secret = st.secrets["binance"]["api_secret"]
    client = Client(api_key, api_secret)
except Exception:
    client = None


@st.cache_data(ttl=600)
def get_binance_klines(symbol="BTCUSDT", interval="1h", limit=1000):
    """Binance API üzerinden OHLCV verisi çeker."""
    if client is None:
        try:
            st.error("Binance API bilgileri bulunamadı. Lütfen `.streamlit/secrets.toml` dosyasını kontrol edin.")
        except Exception:
            print("HATA: Binance API bilgileri bulunamadı. Lütfen `.streamlit/secrets.toml` dosyasını kontrol edin.")
        return pd.DataFrame()

    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
            'Close_time', 'Quote_asset_volume', 'Number_of_trades',
            'Taker_buy_base_asset_volume', 'Taker_buy_quote_asset_volume', 'Ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)
        return df
    except Exception as e:
        try:
            st.error(f"{symbol} için Binance'ten veri çekilirken hata oluştu: {e}")
        except Exception:
             print(f"HATA: {symbol} için Binance'ten veri çekilirken hata oluştu: {e}")
        return pd.DataFrame()

# ... (dosyanın geri kalan fonksiyonları aynı kalacak) ...
def calculate_fibonacci_levels(df):
    """Son 100 barın en yüksek ve en düşük değerlerine göre Fibonacci seviyelerini hesaplar."""
    if df.empty or len(df) < 2:
        return {}

    last_100_bars = df.iloc[-100:]
    max_price = last_100_bars['High'].max()
    min_price = last_100_bars['Low'].min()
    diff = max_price - min_price

    levels = {
        'Fib 0% (High)': max_price,
        'Fib 23.6%': max_price - 0.236 * diff,
        'Fib 38.2%': max_price - 0.382 * diff,
        'Fib 50%': max_price - 0.5 * diff,
        'Fib 61.8%': max_price - 0.618 * diff,
        'Fib 100% (Low)': min_price
    }
    return levels


def _calculate_equity_and_drawdown(trades_df, initial_capital=100):
    """
    Sermaye eğrisini, tepe noktalarını ve düşüş serisini hesaplar.
    Bu bir yardımcı (private) fonksiyondur.
    """
    trades_df_sorted = trades_df.sort_values(by='Çıkış Zamanı').copy()
    trades_df_sorted['pnl_factor'] = trades_df_sorted['Getiri (%)'] / 100
    trades_df_sorted['equity'] = initial_capital * (1 + trades_df_sorted['pnl_factor']).cumprod()

    equity_curve = trades_df_sorted[['Çıkış Zamanı', 'equity']].set_index('Çıkış Zamanı')
    peak = equity_curve['equity'].cummax()
    drawdown_series = (equity_curve['equity'] - peak) / peak

    return equity_curve, drawdown_series


def analyze_backtest_results(trades_df, risk_free_rate=0.02):
    """
    Backtest işlem sonuçlarını analiz eder ve ham (raw) performans metrikleri üretir.
    Görselleştirme için sermaye eğrisi ve düşüş serilerini de döndürür.
    """
    if trades_df.empty or trades_df['Getiri (%)'].isnull().all():
        return {}, None, None

    # --- Temel Metrikler ---
    total_trades = len(trades_df)
    winning_trades_df = trades_df[trades_df['Getiri (%)'] > 0]
    losing_trades_df = trades_df[trades_df['Getiri (%)'] <= 0]

    win_rate = (len(winning_trades_df) / total_trades) * 100 if total_trades > 0 else 0
    total_pnl_pct = trades_df['Getiri (%)'].sum()
    avg_win_pct = winning_trades_df['Getiri (%)'].mean() if not winning_trades_df.empty else 0
    avg_loss_pct = losing_trades_df['Getiri (%)'].mean() if not losing_trades_df.empty else 0
    payoff_ratio = abs(avg_win_pct / avg_loss_pct) if avg_loss_pct != 0 else np.inf

    # --- Sermaye ve Düşüş Hesaplamaları ---
    equity_curve, drawdown_series = _calculate_equity_and_drawdown(trades_df)
    max_drawdown_pct = abs(drawdown_series.min() * 100) if not drawdown_series.empty else 0

    # --- Performans Oranları ---
    daily_returns = equity_curve['equity'].pct_change().dropna()

    # Sharpe Oranı
    sharpe_ratio = 0
    if daily_returns.std() != 0 and pd.notna(daily_returns.std()):
        sharpe_ratio = (daily_returns.mean() * 252) / (daily_returns.std() * np.sqrt(252))

    # Sortino Oranı
    downside_returns = daily_returns[daily_returns < 0]
    downside_std = downside_returns.std()
    sortino_ratio = 0
    if downside_std != 0 and pd.notna(downside_std):
        sortino_ratio = (daily_returns.mean() * 252) / (downside_std * np.sqrt(252))

    # Calmar Oranı
    total_days = (trades_df['Çıkış Zamanı'].max() - trades_df['Giriş Zamanı'].min()).days if total_trades > 1 else 0
    annualized_return = ((equity_curve['equity'].iloc[-1] / 100) ** (
                365.0 / total_days) - 1) * 100 if total_days > 0 else total_pnl_pct
    calmar_ratio = annualized_return / max_drawdown_pct if max_drawdown_pct > 0 else np.inf

    # SONUÇLARI HAM SAYISAL VERİ OLARAK DÖNDÜR
    results = {
        "Toplam İşlem": total_trades,
        "Kazançlı İşlem Oranı (%)": win_rate,
        "Toplam Getiri (%)": total_pnl_pct,
        "Ortalama Kazanç (%)": avg_win_pct,
        "Ortalama Kayıp (%)": avg_loss_pct,
        "Risk/Ödül Oranı (Payoff)": payoff_ratio,
        "Maksimum Düşüş (Drawdown) (%)": max_drawdown_pct,
        "Sharpe Oranı (Yıllık)": sharpe_ratio,
        "Sortino Oranı (Yıllık)": sortino_ratio,
        "Calmar Oranı": calmar_ratio,
    }

    return results, equity_curve, drawdown_series



@st.cache_data(ttl=30)  # Fiyatları 30 saniye önbellekte tut
def get_current_prices(symbols: list):
    """
    Verilen sembol listesi için Binance'den anlık fiyatları çeker.
    """
    if not symbols or client is None:
        return {}

    prices = {}
    try:
        tickers = client.get_symbol_ticker()
        # İhtiyacımız olan sembolleri daha hızlı bulmak için ticker'ları bir sözlüğe dönüştür
        ticker_map = {ticker['symbol']: float(ticker['price']) for ticker in tickers}

        for symbol in symbols:
            if symbol in ticker_map:
                prices[symbol] = ticker_map[symbol]
    except Exception as e:
        # Hata durumunda st.error'ı try-except içine alarak worker'da çökmesini engelle
        try:
            st.error(f"Anlık fiyatlar çekilirken hata oluştu: {e}")
        except Exception:
            print(f"HATA: Anlık fiyatlar çekilirken hata oluştu: {e}")
    return prices

# utils.py dosyasının en üstüne ekleyin (eğer yoksa)
import requests

# utils.py dosyasının sonuna bu iki fonksiyonu ekleyin

@st.cache_data(ttl=3600) # Veriyi 1 saat önbellekte tut
def get_fear_and_greed_index():
    """Kripto Korku ve Hırs Endeksi'ni API'den çeker."""
    try:
        response = requests.get("https://api.alternative.me/fng/?limit=1")
        response.raise_for_status()
        data = response.json()['data'][0]
        return {
            "value": int(data['value']),
            "classification": data['value_classification']
        }
    except Exception as e:
        print(f"HATA: Korku ve Hırs Endeksi alınamadı: {e}")
        return None

@st.cache_data(ttl=900) # Veriyi 15 dakika önbellekte tut
def get_btc_dominance():
    """CoinGecko API üzerinden anlık Bitcoin Dominansı'nı çeker."""
    try:
        response = requests.get("https://api.coingecko.com/api/v3/global")
        response.raise_for_status()
        data = response.json()['data']
        btc_dominance = data['market_cap_percentage'].get('btc')
        return round(btc_dominance, 2) if btc_dominance else None
    except Exception as e:
        print(f"HATA: Bitcoin Dominansı alınamadı: {e}")
        return None