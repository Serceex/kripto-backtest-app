import streamlit as st
import pandas as pd
import numpy as np
import time
import itertools
import random
import threading

from utils import get_binance_klines, calculate_fibonacci_levels
from indicators import generate_all_indicators
from features import prepare_features
from ml_model import SignalML
from signals import generate_signals, backtest_signals
from plots import plot_chart
from telegram_alert import send_telegram_message

st.set_page_config(page_title="Kripto Portföy Backtest + ML + Optimizasyon + Puzzle Bot", layout="wide")
st.title("📊 Kripto Portföy Backtest + ML + Optimizasyon + Puzzle Bot")

# ------------------------------
# UI Sidebar
with st.sidebar.expander("📊 Grafik Gösterge Seçenekleri", expanded=False):
    show_sma = st.checkbox("SMA Göster", value=False)
    sma_period = st.slider("SMA Periyodu", 5, 200, 50)
    show_ema = st.checkbox("EMA Göster", value=False)
    ema_period = st.slider("EMA Periyodu", 5, 200, 20)
    show_bbands = st.checkbox("Bollinger Bands Göster", value=False)
    bb_period = st.slider("BB Periyodu", 5, 60, 20)
    bb_std = st.slider("BB Std Sapma", 1.0, 3.0, 2.0, step=0.1)
    rsi_buy = st.slider("📥 RSI Al Eşiği", 10, 50, 30)
    rsi_sell = st.slider("📤 RSI Sat Eşiği", 50, 90, 70)
    show_vwap = st.checkbox("VWAP Göster", value=False)
    show_adx = st.checkbox("ADX Göster", value=False)
    show_stoch = st.checkbox("Stochastic Göster", value=False)
    show_fibonacci = st.checkbox("Fibonacci Göster", value=False)

    with st.sidebar.expander("🔧 Diğer Parametreler (Genişletmek için tıklayın)", expanded=False):
        st.subheader("🧩 Puzzle Strateji Botu")
        use_puzzle_bot = st.checkbox("Puzzle Strateji Botunu Kullan", value=False, key="puzzle_bot")

        st.subheader("📡 Telegram Bildirimleri")
        use_telegram = st.checkbox("Telegram Bildirimlerini Aç", value=False, key="telegram_alerts")

        st.subheader("🤖 ML Tahmin Parametreleri")
        use_ml = st.checkbox("Makine Öğrenmesi Tahmini Kullan", value=False, key="ml_toggle")

        if use_ml:
            forward_window = st.slider("📈 Gelecek Bar (target)", 1, 20, 5, key="ml_forward_window")
            target_thresh = st.slider("🎯 Target Eşik (%)", 0.1, 5.0, 0.5, step=0.1, key="ml_threshold")

        st.markdown("---")
        if st.button("🔍 Portföy Optimizasyon Başlat", key="optimize_button"):
            best_params, best_score = run_portfolio_optimization(symbols, interval)
            with optimize_section:
                if best_params:
                    st.success(f"""
                    ✅ En iyi parametreler:
                    - RSI Al: {best_params[0]}, RSI Sat: {best_params[1]}
                    - BB Periyodu: {best_params[2]}, BB Std: {best_params[3]}
                    - Ortalama Portföy Getiri: {best_score:.2f}%
                    """)
                else:
                    st.warning("Hiç uygun sonuç bulunamadı.")

st.sidebar.header("🔔 Sinyal Kriterleri Seçenekleri")
col1, col2 = st.sidebar.columns(2)
use_rsi = col1.checkbox("RSI Sinyali", value=True)
use_macd = col2.checkbox("MACD Sinyali", value=True)

col3, col4 = st.sidebar.columns(2)
use_bbands = col3.checkbox("Bollinger Sinyali", value=True)
use_adx = col4.checkbox("ADX Sinyali", value=True)

adx_threshold = st.sidebar.slider("ADX Eşiği", 10, 50, 25)

st.sidebar.header("⚙️ Strateji Gelişmiş Ayarlar")
signal_mode = st.sidebar.selectbox("Sinyal Modu", ["Long Only", "Long & Short"], index=1)
stop_loss_pct = st.sidebar.slider("Stop Loss (%)", 0.1, 10.0, 2.0, step=0.1)
take_profit_pct = st.sidebar.slider("Take Profit (%)", 0.1, 20.0, 5.0, step=0.1)
cooldown_bars = st.sidebar.slider("Cooldown (bar sayısı)", 0, 10, 3)


# ------------------------------
# Üst Ekran Seçimleri
symbols = st.multiselect(
    "📈 Portföyde test edilecek semboller",
    ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "CHZUSDT"],
    default=["BTCUSDT", "ETHUSDT", "SOLUSDT"]
)
interval = st.selectbox("⏳ Zaman Dilimi Seçin", options=["15m", "1h", "4h"], index=1)

# ------------------------------
# Sonuçlar için container
results_section = st.container()
optimize_section = st.container()

# ------------------------------
# Canlı Fiyat ve Sinyal Güncelleme Fonksiyonu (Telegram Bildirimi dahil)
def update_price_live(symbol, interval, placeholder):
    signal_text_map = {
        "Al": "🟢 AL",
        "Sat": "🔴 SAT",
        "Short": "🔴 SAT",
        "Bekle": "⏸️ BEKLE"
    }

    last_signal_sent = None

    while True:
        try:
            df_latest = get_binance_klines(symbol=symbol, interval=interval, limit=20)
            df_temp = generate_all_indicators(df_latest,
                                              sma_period=sma_period,
                                              ema_period=ema_period,
                                              bb_period=bb_period,
                                              bb_std=bb_std)
            df_temp = generate_signals(df_temp,
                                       use_rsi=use_rsi,
                                       rsi_buy=rsi_buy,
                                       rsi_sell=rsi_sell,
                                       use_macd=use_macd,
                                       use_bbands=use_bbands,
                                       use_adx=use_adx,
                                       adx_threshold=adx_threshold,
                                       signal_mode=signal_mode,
                                       use_puzzle_bot=use_puzzle_bot)

            last_price = df_latest['Close'].iloc[-1]
            last_signal = df_temp['Signal'].iloc[-1]

            # Telegram bildirim kontrolü
            if use_telegram and last_signal != last_signal_sent and last_signal != "Bekle":
                message = f"📡 {symbol} için yeni sinyal: *{signal_text_map.get(last_signal, last_signal)}* | Fiyat: {last_price:.2f} USDT"
                send_telegram_message(message)
                last_signal_sent = last_signal

            placeholder.markdown(f"""
            ### 📈 {symbol}
            #### 💰 Güncel Fiyat: `{last_price:,.2f} USDT`
            #### 📡 Sinyal: **{signal_text_map.get(last_signal, '⏸️ BEKLE')}**
            """)

            time.sleep(3)
        except Exception as e:
            placeholder.warning(f"⚠️ Canlı veri hatası: {e}")
            break

# ------------------------------
# Portföy Backtest fonksiyonu (long & short + stop loss/take profit + cooldown + Puzzle Bot)
def run_portfolio_backtest(symbols, interval, strategy_params):
    all_results = []
    for symbol in symbols:
        st.write(f"🔍 {symbol} verisi indiriliyor ve strateji uygulanıyor...")
        df = get_binance_klines(symbol=symbol, interval=interval)
        df = generate_all_indicators(df,
                                     sma_period=strategy_params['sma'],
                                     ema_period=strategy_params['ema'],
                                     bb_period=strategy_params['bb_period'],
                                     bb_std=strategy_params['bb_std'])
        df = generate_signals(df,
                              use_rsi=strategy_params['use_rsi'],
                              rsi_buy=strategy_params['rsi_buy'],
                              rsi_sell=strategy_params['rsi_sell'],
                              use_macd=strategy_params['use_macd'],
                              use_bbands=strategy_params['use_bbands'],
                              use_adx=strategy_params['use_adx'],
                              adx_threshold=strategy_params['adx'],
                              signal_mode=strategy_params['signal_mode'],
                              use_puzzle_bot=strategy_params['use_puzzle_bot'])

        trades = []
        position = None
        entry_price = 0
        entry_time = None
        cooldown = 0

        for i in range(len(df)):
            if cooldown > 0:
                cooldown -= 1
                continue

            signal = df['Signal'].iloc[i]
            price = df['Close'].iloc[i]
            time_idx = df.index[i]

            if position is None:
                if signal == 'Al':
                    position = 'Long'
                    entry_price = price
                    entry_time = time_idx
                elif signal == 'Short' and strategy_params['signal_mode'] == "Long & Short":
                    position = 'Short'
                    entry_price = price
                    entry_time = time_idx
            elif position == 'Long':
                ret = (price - entry_price) / entry_price * 100
                if (ret <= -strategy_params['stop_loss_pct']) or (ret >= strategy_params['take_profit_pct']) or (signal == 'Sat'):
                    trades.append({
                        'Pozisyon': 'Long',
                        'Giriş Zamanı': entry_time,
                        'Çıkış Zamanı': time_idx,
                        'Giriş Fiyatı': entry_price,
                        'Çıkış Fiyatı': price,
                        'Getiri (%)': round(ret, 2)
                    })
                    position = None
                    cooldown = strategy_params['cooldown_bars']
            elif position == 'Short':
                ret = (entry_price - price) / entry_price * 100
                if (ret <= -strategy_params['stop_loss_pct']) or (ret >= strategy_params['take_profit_pct']) or (signal == 'Al'):
                    trades.append({
                        'Pozisyon': 'Short',
                        'Giriş Zamanı': entry_time,
                        'Çıkış Zamanı': time_idx,
                        'Giriş Fiyatı': entry_price,
                        'Çıkış Fiyatı': price,
                        'Getiri (%)': round(ret, 2)
                    })
                    position = None
                    cooldown = strategy_params['cooldown_bars']

        # Açık pozisyon varsa son olarak ekle
        if position is not None:
            trades.append({
                'Pozisyon': position,
                'Giriş Zamanı': entry_time,
                'Çıkış Zamanı': pd.NaT,
                'Giriş Fiyatı': entry_price,
                'Çıkış Fiyatı': np.nan,
                'Getiri (%)': np.nan
            })

        if trades:
            results_df = pd.DataFrame(trades)
            results_df['Sembol'] = symbol
            all_results.append(results_df)

    if all_results:
        portfolio_results = pd.concat(all_results).sort_values("Giriş Zamanı")
        total_return = portfolio_results['Getiri (%)'].sum()
        avg_trade = portfolio_results['Getiri (%)'].mean()
        win_rate = (portfolio_results['Getiri (%)'] > 0).mean() * 100

        st.subheader("📊 Portföy Backtest Sonuçları")
        st.dataframe(portfolio_results)

        st.markdown(f"""
        #### 🚀 Portföy Performansı
        - Toplam İşlem: `{len(portfolio_results)}`
        - Toplam Portföy Getiri: `{total_return:.2f}%`
        - Ortalama İşlem: `{avg_trade:.2f}%`
        - Kazançlı İşlem Oranı: `{win_rate:.1f}%`
        """)
    else:
        st.warning("Hiç işlem bulunamadı.")

# ------------------------------
# Basit Optimizasyon fonksiyonu örneği
def run_portfolio_optimization(symbols, interval):
    rsi_buy_vals = list(range(10, 51, 5))
    rsi_sell_vals = list(range(50, 91, 5))
    bb_period_vals = list(range(5, 61, 5))
    bb_std_vals = [round(x * 0.1, 1) for x in range(10, 31, 2)]

    param_grid = list(itertools.product(rsi_buy_vals, rsi_sell_vals, bb_period_vals, bb_std_vals))
    st.sidebar.write(f"🔄 Toplam Kombinasyon: {len(param_grid)}")

    if len(param_grid) > 100:
        param_grid = random.sample(param_grid, 100)

    best_score = -np.inf
    best_params = None
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()

    for i, (rsi_b, rsi_s, bb_p, bb_st) in enumerate(param_grid):
        all_results = []
        for symbol in symbols:
            df = get_binance_klines(symbol=symbol, interval=interval)
            df = generate_all_indicators(df, sma_period=50, ema_period=20, bb_period=bb_p, bb_std=bb_st)
            df = generate_signals(df, use_rsi=True, rsi_buy=rsi_b, rsi_sell=rsi_s,
                                  use_macd=True, use_bbands=True, use_adx=True, adx_threshold=25, signal_mode="Long Only")
            results = backtest_signals(df)
            if not results.empty:
                all_results.append(results)
        if all_results:
            portfolio_results = pd.concat(all_results)
            avg_return = portfolio_results['Getiri (%)'].mean()
            if avg_return > best_score:
                best_score = avg_return
                best_params = (rsi_b, rsi_s, bb_p, bb_st)

        progress_bar.progress(int((i + 1) / len(param_grid) * 100))
        status_text.text(f"RSI {rsi_b}/{rsi_s} BB {bb_p}/{bb_st} En İyi: {best_score:.2f}%")
        time.sleep(0.05)

    status_text.text("🚀 Optimizasyon tamamlandı!")
    progress_bar.empty()
    return best_params, best_score

# ------------------------------
# Butonlar ve container yönetimi
with st.sidebar:
    if st.button("🚀 Portföy Backtest Başlat"):
        strategy_params = {
            'sma': sma_period,
            'ema': ema_period,
            'bb_period': bb_period,
            'bb_std': bb_std,
            'use_rsi': use_rsi,
            'rsi_buy': rsi_buy,
            'rsi_sell': rsi_sell,
            'use_macd': use_macd,
            'use_bbands': use_bbands,
            'use_adx': use_adx,
            'adx': adx_threshold,
            'signal_mode': signal_mode,
            'stop_loss_pct': stop_loss_pct,
            'take_profit_pct': take_profit_pct,
            'cooldown_bars': cooldown_bars,
            'use_puzzle_bot': use_puzzle_bot
        }
        with results_section:
            run_portfolio_backtest(symbols, interval, strategy_params)

# ------------------------------
# Tek sembol için detaylı grafik & ML & Canlı sinyal
if len(symbols) == 1:
    symbol = symbols[0]
    price_placeholder = st.empty()

    threading.Thread(
        target=update_price_live,
        args=(symbol, interval, price_placeholder),
        daemon=True
    ).start()

    df = get_binance_klines(symbol=symbol, interval=interval)
    df = generate_all_indicators(df, sma_period, ema_period, bb_period, bb_std)
    df = generate_signals(df, use_rsi, rsi_buy, rsi_sell, use_macd, use_bbands, use_adx, adx_threshold, signal_mode=signal_mode, use_puzzle_bot=use_puzzle_bot)
    fib_levels = calculate_fibonacci_levels(df)

    if use_ml:
        X, y, df = prepare_features(df, forward_window, target_thresh)
        if len(X) > 20:
            model = SignalML()
            model.train(X, y)
            df.loc[X.index, 'ML_Signal'] = model.predict_signals(X)
        else:
            df['ML_Signal'] = 0
    else:
        df['ML_Signal'] = 0

    last_price = df['Close'].iloc[-1]
    st.subheader(f"Detaylı Grafik & ML Tahmini — Güncel Fiyat: {last_price:.2f} USDT")

    options = {
        "show_sma": show_sma,
        "show_ema": show_ema,
        "show_bbands": show_bbands,
        "show_vwap": show_vwap,
        "show_adx": show_adx,
        "show_stoch": show_stoch,
        "show_fibonacci": show_fibonacci,
    }
    st.plotly_chart(plot_chart(df, symbol, fib_levels, options, ml_signal=use_ml), use_container_width=True)
    st.subheader("📌 Son 5 Sinyal")
    st.dataframe(df[['Close', 'RSI', 'MACD', 'MACD_signal', 'Signal', 'ADX', 'ML_Signal']].tail(5), use_container_width=True)
