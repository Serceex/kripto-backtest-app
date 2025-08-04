from binance.client import Client
import pandas as pd
import streamlit as st
import numpy as np

# API bilgilerini streamlit secrets'tan al
api_key = st.secrets["binance"]["api_key"]
api_secret = st.secrets["binance"]["api_secret"]

# Binance istemcisini oluştur
#client = Client(api_key, api_secret)
client = Client(api_key, api_secret, testnet=True)
client.API_URL = 'https://testnet.binance.vision/api'


def get_binance_klines(symbol="BTCUSDT", interval="1h", limit=1000):
    """Binance API üzerinden OHLCV verisi çeker"""
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)

    # DataFrame'e dönüştür
    df = pd.DataFrame(klines, columns=[
        'timestamp', 'Open', 'High', 'Low', 'Close', 'Volume',
        'Close_time', 'Quote_asset_volume', 'Number_of_trades',
        'Taker_buy_base_asset_volume', 'Taker_buy_quote_asset_volume', 'Ignore'
    ])

    # Tip dönüşümleri ve timestamp düzenleme
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].astype(float)

    return df

def calculate_fibonacci_levels(df):
    max_price = df['High'][-100:].max()
    min_price = df['Low'][-100:].min()
    diff = max_price - min_price
    levels = {
        '0%': max_price,
        '23.6%': max_price - 0.236 * diff,
        '38.2%': max_price - 0.382 * diff,
        '50%': max_price - 0.5 * diff,
        '61.8%': max_price - 0.618 * diff,
        '100%': min_price
    }
    return levels


# utils.py dosyasındaki analyze_backtest_results fonksiyonunun YENİ HALİ

def analyze_backtest_results(trades_df, risk_free_rate=0.02):
    """
    Backtest işlem sonuçlarını analiz eder ve profesyonel performans metrikleri üretir.
    Ayrıca görselleştirme için sermaye eğrisi ve düşüş serilerini de döndürür.
    """
    if trades_df.empty or trades_df['Getiri (%)'].isnull().all():
        return {}, None, None  # Metrikler ve seriler için boş döndür

    # Temel Metrikler
    total_trades = len(trades_df)
    winning_trades = trades_df[trades_df['Getiri (%)'] > 0]
    losing_trades = trades_df[trades_df['Getiri (%)'] <= 0]

    win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
    total_pnl_pct = trades_df['Getiri (%)'].sum()
    avg_win_pct = winning_trades['Getiri (%)'].mean() if not winning_trades.empty else 0
    avg_loss_pct = losing_trades['Getiri (%)'].mean() if not losing_trades.empty else 0

    payoff_ratio = abs(avg_win_pct / avg_loss_pct) if avg_loss_pct != 0 else float('inf')

    # Sermaye Eğrisi (Equity Curve) Hesaplaması
    initial_capital = 100
    trades_df['pnl_factor'] = trades_df['Getiri (%)'] / 100

    # Kümülatif getiri hesaplaması için 'Çıkış Zamanı'na göre sırala
    trades_df_sorted = trades_df.sort_values(by='Çıkış Zamanı')
    trades_df_sorted['equity'] = initial_capital * (1 + trades_df_sorted['pnl_factor']).cumprod()
    equity_curve = trades_df_sorted[['Çıkış Zamanı', 'equity']].set_index('Çıkış Zamanı')

    # Maksimum Düşüş (Maximum Drawdown)
    peak = equity_curve['equity'].cummax()
    drawdown_series = (equity_curve['equity'] - peak) / peak
    max_drawdown_pct = abs(drawdown_series.min() * 100) if not drawdown_series.empty else 0

    # Sharpe & Sortino Oranları
    daily_returns = equity_curve['equity'].pct_change().dropna()

    sharpe_ratio = 0
    if daily_returns.std() != 0 and daily_returns.std() is not np.nan:
        sharpe_ratio = (daily_returns.mean() * 252) / (daily_returns.std() * np.sqrt(252))

    downside_returns = daily_returns[daily_returns < 0]
    downside_std = downside_returns.std()
    sortino_ratio = 0
    if downside_std != 0 and downside_std is not np.nan:
        sortino_ratio = (daily_returns.mean() * 252) / (downside_std * np.sqrt(252))

    # Calmar Oranı
    total_days = (trades_df['Çıkış Zamanı'].max() - trades_df['Giriş Zamanı'].min()).days if total_trades > 1 else 0
    annualized_return = ((equity_curve['equity'].iloc[-1] / initial_capital) ** (
                365.0 / total_days) - 1) * 100 if total_days > 0 else total_pnl_pct
    calmar_ratio = annualized_return / max_drawdown_pct if max_drawdown_pct > 0 else float('inf')

    results = {
        "Toplam İşlem": total_trades,
        "Kazançlı İşlem Oranı (%)": f"{win_rate:.2f}",
        "Toplam Getiri (%)": f"{total_pnl_pct:.2f}",
        "Ortalama Kazanç (%)": f"{avg_win_pct:.2f}",
        "Ortalama Kayıp (%)": f"{avg_loss_pct:.2f}",
        "Risk/Ödül Oranı (Payoff)": f"{payoff_ratio:.2f}",
        "Maksimum Düşüş (Drawdown) (%)": f"{max_drawdown_pct:.2f}",
        "Sharpe Oranı (Yıllık)": f"{sharpe_ratio:.2f}",
        "Sortino Oranı (Yıllık)": f"{sortino_ratio:.2f}",
        "Calmar Oranı": f"{calmar_ratio:.2f}",
    }

    return results, equity_curve, drawdown_series
