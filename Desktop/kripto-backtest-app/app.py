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
from signals import generate_signals, backtest_signals, create_signal_column
from plots import plot_chart
from telegram_alert import send_telegram_message
from alarm_log import log_alarm, get_alarm_history

st.set_page_config(page_title="Kripto Portföy Backtest", layout="wide")
st.title("📊 Kripto Portföy Backtest + ML + Optimizasyon + Puzzle Bot")

st.sidebar.header("🔎 Menü Seçimi")
page = st.sidebar.radio("Sayfa", ["Portföy Backtest", "Canlı İzleme", "Optimizasyon"])

if "live_tracking" not in st.session_state:
    st.session_state.live_tracking = False  # Başlangıçta izleme kapalı

with st.sidebar.expander("📊 Grafik Gösterge Seçenekleri", expanded=False):
    show_sma = st.checkbox("SMA Göster", value=False)
    sma_period = st.slider("SMA Periyodu", 5, 200, 50)
    show_ema = st.checkbox("EMA Göster", value=False)
    ema_period = st.slider("EMA Periyodu", 5, 200, 20)
    show_bbands = st.checkbox("Bollinger Bands Göster", value=False)
    bb_period = st.slider("BB Periyodu", 5, 60, 20)
    bb_std = st.slider("BB Std Sapma", 1.0, 3.0, 2.0, step=0.1)
    rsi_buy_chart = st.slider("📥 RSI Al Eşiği", 10, 50, 30)
    rsi_sell_chart = st.slider("📤 RSI Sat Eşiği", 50, 90, 70)
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
    else:
        forward_window = None
        target_thresh = None

st.sidebar.header("🔔 Sinyal Kriterleri Seçenekleri")

col1, col2 = st.sidebar.columns(2)
use_rsi = col1.checkbox("RSI Sinyali", value=True, key='use_rsi')
use_macd = col2.checkbox("MACD Sinyali", value=True, key='use_macd')

col3, col4 = st.sidebar.columns(2)
use_bb = col3.checkbox("Bollinger Sinyali", value=True, key='use_bb')
use_adx = col4.checkbox("ADX Sinyali", value=True, key='use_adx')

if use_rsi:
    rsi_period = st.sidebar.number_input("RSI Periyodu", min_value=2, max_value=100, value=14)
    rsi_buy = st.sidebar.slider("RSI Alış Eşiği", min_value=0, max_value=50, value=30, step=1)
    rsi_sell = st.sidebar.slider("RSI Satış Eşiği", min_value=50, max_value=100, value=70, step=1)
else:
    # Default değerler (kullanılmayacak çünkü use_rsi False)
    rsi_buy = 30
    rsi_sell = 70
    rsi_period = 14

if use_macd:
    macd_fast = st.sidebar.slider("MACD Fast Periyodu", 5, 20, 12)
    macd_slow = st.sidebar.slider("MACD Slow Periyodu", 10, 40, 26)
    macd_signal = st.sidebar.slider("MACD Signal Periyodu", 5, 15, 9)
else:
    macd_fast = 12
    macd_slow = 26
    macd_signal = 9

adx_threshold = st.sidebar.slider("ADX Eşiği", 10, 50, 25)

# Üst ekran sembol ve interval seçimi (sabit)
symbols = st.multiselect(
    "📈 Portföyde test edilecek semboller",
    [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT", "DOGEUSDT",
        "MATICUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT", "SHIBUSDT", "AVAXUSDT", "UNIUSDT",
        "LINKUSDT", "ALGOUSDT", "ATOMUSDT", "BCHUSDT", "XLMUSDT", "VETUSDT", "FILUSDT",
        "ICPUSDT", "THETAUSDT", "EOSUSDT", "AAVEUSDT", "MKRUSDT", "KSMUSDT", "XTZUSDT",
        "NEARUSDT", "CAKEUSDT", "FTMUSDT", "GRTUSDT", "SNXUSDT", "RUNEUSDT", "CHZUSDT",
        "ZILUSDT", "DASHUSDT", "SANDUSDT", "KAVAUSDT", "COMPUSDT", "LUNAUSDT", "ENJUSDT",
        "BATUSDT", "NANOUSDT", "1INCHUSDT", "ZRXUSDT", "CELRUSDT", "HNTUSDT", "FTTUSDT",
        "GALAUSDT"
    ],
    default=["BTCUSDT", "ETHUSDT"]
)

interval = st.selectbox("⏳ Zaman Dilimi Seçin", options=["15m", "1h", "4h"], index=1)

# Container’lar
results_section = st.container()
optimize_section = st.container()

st.header("⚙️ Strateji Gelişmiş Ayarlar")

col1, col2, col3, col4 = st.columns(4)

with col1:
    signal_mode = st.selectbox("Sinyal Modu", ["Long Only", "Short Only", "Long & Short"], index=2)

    signal_direction = {
        "Long Only": "Long",
        "Short Only": "Short",
        "Long & Short": "Both"
    }[signal_mode]

with col2:
    stop_loss_pct = st.slider("Stop Loss (%)", 0.1, 10.0, 2.0, step=0.1)

with col3:
    take_profit_pct = st.slider("Take Profit (%)", 0.1, 20.0, 5.0, step=0.1)

with col4:
    cooldown_bars = st.slider("Cooldown (bar sayısı)", 0, 10, 3)

# Strateji parametrelerini hazırla
strategy_params = {
    'sma': sma_period,
    'ema': ema_period,
    'bb_period': bb_period,
    'bb_std': bb_std,

    'rsi_buy': rsi_buy,
    'rsi_sell': rsi_sell,
    'rsi_period': rsi_period,
    'macd_fast': macd_fast,
    'macd_slow': macd_slow,
    'macd_signal': macd_signal,
    'adx_period': 14,
    'adx_threshold': adx_threshold,
    'use_rsi': use_rsi,
    'use_macd': use_macd,
    'use_bb': use_bb,
    'use_adx': use_adx,

    'stop_loss_pct': stop_loss_pct,
    'take_profit_pct': take_profit_pct,
    'cooldown_bars': cooldown_bars,

    'signal_mode': signal_mode,
    'signal_direction': signal_direction,
    'use_puzzle_bot': use_puzzle_bot,
    'use_ml': use_ml
}

# ------------------------------
# Canlı İzleme Thread Yönetimi için session_state default değerleri

if "live_running" not in st.session_state:
    st.session_state.live_running = False

if "live_thread_started" not in st.session_state:
    st.session_state.live_thread_started = False

if "last_signal" not in st.session_state:
    st.session_state.last_signal = "Henüz sinyal yok."

# Backtest sonuçlarını session_state'de saklamak için başlangıç
if "backtest_results" not in st.session_state:
    st.session_state.backtest_results = pd.DataFrame()


# ------------------------------
# Fonksiyonlar

def update_price_live(symbol, interval, placeholder):
    signal_text_map = {
        "Al": "🟢 AL",
        "Sat": "🔴 SAT",
        "Short": "🔴 SAT",
        "Bekle": "⏸️ BEKLE"
    }
    last_signal_sent = None
    while st.session_state.live_running:
        try:
            df_latest = get_binance_klines(symbol=symbol, interval=interval, limit=20)
            if df_latest is None or df_latest.empty:
                placeholder.warning(f"{symbol} için canlı veri alınamıyor.")
                time.sleep(5)
                continue

            df = generate_all_indicators(
                df,
                strategy_params["rsi_period"],
                strategy_params["macd_fast"],
                strategy_params["macd_slow"],
                strategy_params["macd_signal"],
                strategy_params["adx_period"]
            )

            df_temp = generate_signals(df_temp,
                                       use_rsi=st.session_state.get('use_rsi', True),
                                       rsi_buy=st.session_state.get('rsi_buy', 30),
                                       rsi_sell=st.session_state.get('rsi_sell', 70),
                                       use_macd=st.session_state.get('use_macd', True),
                                       use_bb=st.session_state.get('use_bb', True),
                                       use_adx=st.session_state.get('use_adx', True),
                                       adx_threshold=st.session_state.get('adx', 25),
                                       signal_mode=signal_mode,
                                       signal_direction=signal_direction,
                                       use_puzzle_bot=st.session_state.get('use_puzzle_bot', False))

            last_price = df_latest['Close'].iloc[-1]
            last_signal = df_temp['Signal'].iloc[-1]

            if st.session_state.get('use_telegram',
                                    False) and last_signal != last_signal_sent and last_signal != "Bekle":
                message = f"📡 {symbol} için yeni sinyal: *{signal_text_map.get(last_signal, last_signal)}* | Fiyat: {last_price:.2f} USDT"
                send_telegram_message(message)
                last_signal_sent = last_signal

            placeholder.markdown(f"""
            ### 📈 {symbol}
            #### 💰 Güncel Fiyat: `{last_price:,.2f} USDT`
            #### 📡 Sinyal: **{signal_text_map.get(last_signal, '⏸️ BEKLE')}**
            """)
            st.session_state.last_signal = f"{symbol}: {signal_text_map.get(last_signal, 'Bekle')} @ {last_price:.2f}"

            time.sleep(3)
        except Exception as e:
            placeholder.warning(f"⚠️ Canlı veri hatası: {e}")
            break


def run_portfolio_backtest(symbols, interval, strategy_params):
    all_results = []
    st.session_state.backtest_data = {}

    for symbol in symbols:
        st.write(f"🔍 {symbol} verisi indiriliyor ve strateji uygulanıyor...")

        df = get_binance_klines(symbol=symbol, interval=interval)
        if df is not None and not df.empty:

            df = generate_all_indicators(
                df,
                strategy_params['sma'],
                strategy_params['ema'],
                strategy_params['bb_period'],
                strategy_params['bb_std'],
                strategy_params['rsi_period'],
                strategy_params['macd_fast'],
                strategy_params['macd_slow'],
                strategy_params['macd_signal'],
                strategy_params['adx_period']
            )

            df = generate_signals(
                df,
                use_rsi=strategy_params["use_rsi"],
                rsi_buy=strategy_params["rsi_buy"],
                rsi_sell=strategy_params["rsi_sell"],
                use_macd=strategy_params["use_macd"],
                use_bb=strategy_params["use_bb"],
                use_adx=strategy_params["use_adx"],
                adx_threshold=strategy_params["adx_threshold"],
                signal_mode=strategy_params["signal_mode"],
                signal_direction=strategy_params["signal_direction"],
                use_puzzle_bot=strategy_params["use_puzzle_bot"]
            )

            trades = []
            position = None
            entry_price = 0
            entry_time = None
            cooldown = 0

            for i in range(len(df)):
                if cooldown > 0:
                    cooldown -= 1
                    continue

                signal = df['Signal'].iloc[i] if 'Signal' in df.columns else 'Bekle'
                price = df['Close'].iloc[i]
                time_idx = df.index[i]

                if position is None:
                    if signal == 'Al' and strategy_params['signal_direction'] != 'Short':
                        position = 'Long'
                        entry_price = price
                        entry_time = time_idx
                    elif signal == 'Sat' and strategy_params['signal_direction'] != 'Long':
                        position = 'Short'
                        entry_price = price
                        entry_time = time_idx

                elif position == 'Long':
                    ret = (price - entry_price) / entry_price * 100
                    if (ret <= -strategy_params['stop_loss_pct']) or (ret >= strategy_params['take_profit_pct']) or (
                            signal == 'Sat'):
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
                    if (ret <= -strategy_params['stop_loss_pct']) or (ret >= strategy_params['take_profit_pct']) or (
                            signal == 'Al'):
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
                st.session_state['backtest_results'] = portfolio_results
            else:
                st.session_state['backtest_results'] = pd.DataFrame()


def live_signal_loop(symbols, interval, params, delay=60):
    last_signal_sent = {}
    while st.session_state.live_running:
        for symbol in symbols:
            try:
                df = get_binance_klines(symbol, interval, limit=100)
                if df is None or df.empty:
                    continue
                df = generate_all_indicators(df,
                                             sma_period=params.get('sma', 50),
                                             ema_period=params.get('ema', 20),
                                             bb_period=params.get('bb_period', 20),
                                             bb_std=params.get('bb_std', 2.0))
                signal_df = generate_signals(df,
                                             use_rsi=params.get('use_rsi', True),
                                             use_macd=params.get('use_macd', True),
                                             use_bb=params.get('use_bb', True),
                                             use_adx=params['use_adx'],
                                             adx_threshold=params.get('adx', 25),
                                             signal_mode=params.get('signal_mode', 'and'),
                                             signal_direction=params.get('signal_direction', 'Long & Short'),
                                             use_puzzle_bot=params.get('use_puzzle_bot', False)
                                             )
                last_signal = signal_df['Signal'].iloc[-1]
                if last_signal in ["Al", "Sat", "Short"]:
                    if last_signal_sent.get(symbol, None) != last_signal:
                        msg = f"{symbol} için yeni sinyal: {last_signal}"
                        if params.get('use_telegram', False):
                            send_telegram_message(msg)
                        log_alarm(symbol, last_signal)
                        st.session_state.last_signal = msg
                        last_signal_sent[symbol] = last_signal
            except Exception as e:
                pass
        time.sleep(delay)


def run_portfolio_optimization(symbols, interval):
    default_rsi_period = 14
    default_macd_fast = 12
    default_macd_slow = 26
    default_macd_signal = 9
    default_adx_period = 14

    use_rsi_opt = st.session_state.get('use_rsi', False)
    use_macd_opt = st.session_state.get('use_macd', False)
    use_bb_opt = st.session_state.get('use_bb', False)
    use_adx_opt = st.session_state.get('use_adx', False)

    param_ranges = {}
    if use_rsi_opt:
        param_ranges['rsi_buy'] = list(range(20, 41, 5))
        param_ranges['rsi_sell'] = list(range(60, 81, 5))
    if use_bb_opt:
        param_ranges['bb_period'] = list(range(10, 31, 5))
        param_ranges['bb_std'] = [round(x * 0.1, 1) for x in range(15, 26, 5)]
    if use_adx_opt:
        param_ranges['adx_threshold'] = list(range(20, 41, 5))

    param_ranges['use_rsi'] = [use_rsi_opt]
    param_ranges['use_macd'] = [use_macd_opt]
    param_ranges['use_bb'] = [use_bb_opt]
    param_ranges['use_adx'] = [use_adx_opt]

    param_ranges['macd_fast'] = [12];
    param_ranges['macd_slow'] = [26];
    param_ranges['macd_signal'] = [9]
    param_ranges['sma'] = [50];
    param_ranges['ema'] = [20]
    param_ranges['signal_mode'] = ['Long & Short'];
    param_ranges['signal_direction'] = ['Both']
    param_ranges['stop_loss_pct'] = [2.0];
    param_ranges['take_profit_pct'] = [5.0]
    param_ranges['cooldown_bars'] = [3];
    param_ranges['use_puzzle_bot'] = [False];
    param_ranges['use_ml'] = [False]

    keys, values = zip(*param_ranges.items())
    param_grid_tuples = itertools.product(*values)
    param_grid = [dict(zip(keys, vals)) for vals in param_grid_tuples]
    st.sidebar.write(f"🔄 Toplam Kombinasyon: {len(param_grid)}")

    max_samples = 500
    if len(param_grid) > max_samples:
        st.sidebar.warning(f"Çok fazla kombinasyon ({len(param_grid)}). Rastgele {max_samples} test ediliyor.")
        param_grid = random.sample(param_grid, max_samples)

    best_score = -np.inf
    best_params = None
    progress_bar = st.sidebar.progress(0)
    status_text = st.sidebar.empty()

    for i, params in enumerate(param_grid):
        all_results = []
        for symbol in symbols:
            df = get_binance_klines(symbol=symbol, interval=interval)
            if df is None or df.empty: continue

            df = generate_all_indicators(df, sma_period=params['sma'], ema_period=params['ema'],
                                         bb_period=params.get('bb_period', 20), bb_std=params.get('bb_std', 2.0),
                                         rsi_period=default_rsi_period, macd_fast=default_macd_fast,
                                         macd_slow=default_macd_slow, macd_signal=default_macd_signal,
                                         adx_period=default_adx_period)

            df = generate_signals(df, use_rsi=params['use_rsi'], rsi_buy=params.get('rsi_buy', 30),
                                  rsi_sell=params.get('rsi_sell', 70), use_macd=params['use_macd'],
                                  use_bb=params['use_bb'], use_adx=params['use_adx'],
                                  adx_threshold=params.get('adx_threshold', 25),
                                  use_puzzle_bot=params['use_puzzle_bot'],
                                  signal_mode=params['signal_mode'],
                                  signal_direction=params['signal_direction'])
            trades = []
            position = None
            entry_price = 0
            entry_time = None
            cooldown = 0
            for k in range(len(df)):
                if cooldown > 0:
                    cooldown -= 1
                    continue
                signal = df['Signal'].iloc[k]
                price = df['Close'].iloc[k]
                time_idx = df.index[k]
                if position is None:
                    if signal == 'Al' and params['signal_direction'] != 'Short':
                        position = 'Long';
                        entry_price = price;
                        entry_time = time_idx
                    elif signal == 'Sat' and params['signal_direction'] != 'Long':
                        position = 'Short';
                        entry_price = price;
                        entry_time = time_idx
                elif position == 'Long':
                    ret = (price - entry_price) / entry_price * 100
                    if (ret <= -params['stop_loss_pct']) or (ret >= params['take_profit_pct']) or (signal == 'Sat'):
                        trades.append({'Pozisyon': 'Long', 'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                                       'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': price, 'Getiri (%)': round(ret, 2)})
                        position = None;
                        cooldown = params['cooldown_bars']
                elif position == 'Short':
                    ret = (entry_price - price) / entry_price * 100
                    if (ret <= -params['stop_loss_pct']) or (ret >= params['take_profit_pct']) or (signal == 'Al'):
                        trades.append({'Pozisyon': 'Short', 'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                                       'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': price, 'Getiri (%)': round(ret, 2)})
                        position = None;
                        cooldown = params['cooldown_bars']
            if trades:
                results_df = pd.DataFrame(trades)
                results_df['Sembol'] = symbol
                all_results.append(results_df)

        if all_results:
            portfolio_results = pd.concat(all_results)
            current_score = portfolio_results['Getiri (%)'].mean()
            if current_score > best_score:
                best_score = current_score
                best_params = params

        progress_text = (
            f"İlerleme: {int((i + 1) / len(param_grid) * 100)}% | "
            f"RSI: {params['use_rsi']} ({params.get('rsi_buy', 'N/A')}/{params.get('rsi_sell', 'N/A')}) | "
            f"BB: {params['use_bb']} ({params.get('bb_period', 'N/A')}/{params.get('bb_std', 'N/A')}) | "
            f"ADX: {params['use_adx']} ({params.get('adx_threshold', 'N/A')}) | "
            f"MACD: {params['use_macd']} | "
            f"En İyi Skor: {best_score:.2f}%"
        )
        progress_bar.progress(int((i + 1) / len(param_grid) * 100))
        status_text.text(progress_text)
        time.sleep(0.01)

    status_text.text("🚀 Optimizasyon tamamlandı!")
    progress_bar.empty()
    return best_params, best_score


# ------------------------------
# Ana Sayfa Menü Yönetimi

if page == "Portföy Backtest":
    st.header("🚀 Portföy Backtest")

    st.session_state.selected_symbols = symbols

    if st.button("Portföy Backtest Başlat"):
        run_portfolio_backtest(symbols, interval, strategy_params)

    if 'backtest_results' in st.session_state and not st.session_state['backtest_results'].empty:
        portfolio_results = st.session_state['backtest_results']
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
        st.info("Backtest sonuçları burada görünecek. Lütfen 'Portföy Backtest Başlat' butonuna basın.")

elif page == "Canlı İzleme":
    st.header("📡 Canlı Sinyal İzleme")

    if "live_tracking" not in st.session_state:
        st.session_state.live_tracking = False

    if st.session_state.live_tracking:
        st.success("🔔 Durum: Sinyal İzleniyor")
    else:
        st.warning("⏹️ Durum: İzleme Kapalı")

    if "selected_symbols" in st.session_state:
        symbols = st.session_state.selected_symbols
        st.markdown(f"**🎯 İzlenen Semboller:** {', '.join(symbols)}")
    else:
        st.error("ℹ️ Lütfen önce Ana Sayfadan sembolleri girin ve Backtest yapın.")

    col1, col2 = st.columns(2)
    if col1.button("▶️ Başlat"):
        if "selected_symbols" in st.session_state:
            st.session_state.live_tracking = True
            st.success("🔁 Canlı sinyal takibi başlatıldı.")
        else:
            st.warning("Önce sembolleri girip backtest başlatmalısınız.")

    if col2.button("⏹️ Durdur"):
        st.session_state.live_tracking = False
        st.info("⏸️ İzleme durduruldu.")

        if "live_running" not in st.session_state:
            st.session_state.live_running = False
        if "live_thread" not in st.session_state:
            st.session_state.live_thread = None

        col1, col2 = st.columns(2)
        start_clicked = col1.button("▶️ Canlı İzlemeyi Başlat")
        stop_clicked = col2.button("⏹️ Canlı İzlemeyi Durdur")

        placeholder = st.empty()

        if start_clicked and not st.session_state.live_running:
            st.session_state.live_running = True


            def live_thread_func():
                while st.session_state.live_running:
                    try:
                        live_data = []
                        for symbol in symbols:
                            df_latest = get_binance_klines(symbol, interval="1m", limit=20)
                            if df_latest is None or df_latest.empty:
                                continue
                            last_price = df_latest['Close'].iloc[-1]
                            signal = "Al" if last_price % 2 == 0 else "Sat"
                            live_data.append({
                                "Sembol": symbol,
                                "Fiyat": f"{last_price:.2f}",
                                "Sinyal": signal
                            })
                        if live_data:
                            placeholder.dataframe(live_data, use_container_width=True)
                        else:
                            placeholder.info("Veri alınamadı.")
                        time.sleep(3)
                    except Exception as e:
                        placeholder.error(f"Hata: {e}")
                        break


            import threading

            t = threading.Thread(target=live_thread_func, daemon=True)
            t.start()
            st.session_state.live_thread = t

        if stop_clicked and st.session_state.live_running:
            st.session_state.live_running = False
            st.session_state.live_thread = None
            placeholder.empty()
            st.success("⛔ Canlı izleme durduruldu.")




elif page == "Optimizasyon":
    st.header("⚙️ Parametre Optimizasyonu")

    if st.button("Optimizasyonu Başlat"):
        best_params, best_score = run_portfolio_optimization(symbols, interval)
        st.success(f"Optimizasyon tamamlandı!")
        if best_params:
            st.write("En İyi Parametreler:")
            st.json(best_params)
            st.write(f"En İyi Ortalama Getiri: {best_score:.2f}%")
        else:
            st.warning("Uygun bir sonuç bulunamadı.")

    st.info("Optimizasyon büyük veri indirme gerektirir, lütfen sabırlı olun.")

if len(symbols) == 1:
    symbol = symbols[0]
    price_placeholder = st.empty()

    # Canlı fiyat güncellemesi için thread (bu kısım aynı kalabilir)
    if 'live_running_chart' not in st.session_state:
        st.session_state.live_running_chart = True
    threading.Thread(
        target=update_price_live,
        args=(symbol, interval, price_placeholder),
        daemon=True
    ).start()

    df = get_binance_klines(symbol=symbol, interval=interval)
    if df is not None and not df.empty:
        # 1. Tüm göstergeleri hesapla
        df = generate_all_indicators(
            df,
            sma_period=sma_period, ema_period=ema_period, bb_period=bb_period, bb_std=bb_std,
            rsi_period=rsi_period, macd_fast=macd_fast, macd_slow=macd_slow,
            macd_signal=macd_signal, adx_period=14
        )

        # 2. Sinyalleri Hesapla
        df = generate_signals(
            df,
            use_rsi=strategy_params["use_rsi"],
            rsi_buy=strategy_params["rsi_buy"],
            rsi_sell=strategy_params["rsi_sell"],
            use_macd=strategy_params["use_macd"],
            use_bb=strategy_params["use_bb"],
            use_adx=strategy_params["use_adx"],
            adx_threshold=strategy_params["adx_threshold"],
            signal_mode=strategy_params["signal_mode"],
            signal_direction=strategy_params["signal_direction"],
            use_puzzle_bot=strategy_params["use_puzzle_bot"]
        )

        fib_levels = calculate_fibonacci_levels(df)

        if strategy_params.get('use_ml', False):
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
            "show_sma": show_sma, "show_ema": show_ema, "show_bbands": show_bbands,
            "show_vwap": show_vwap, "show_adx": show_adx, "show_stoch": show_stoch,
            "show_fibonacci": show_fibonacci,
        }
        st.plotly_chart(plot_chart(df, symbol, fib_levels, options, ml_signal=strategy_params.get('use_ml', False)),
                        use_container_width=True)

        # --- YENİ VE GELİŞTİRİLMİŞ "SON SİNYALLER" BÖLÜMÜ ---
        st.subheader("📌 Son Gerçekleşen 5 Sinyal")

        # Sadece 'Al' veya 'Sat' olan sinyalleri filtrele
        recent_signals = df[df['Signal'].isin(['Al', 'Sat'])].tail(5)

        if not recent_signals.empty:
            # Gösterim için yeni bir DataFrame oluştur
            display_df = recent_signals[['Signal', 'Close', 'RSI', 'MACD', 'ADX']].copy()

            # Kolon isimlerini Türkçeleştir
            display_df.rename(columns={
                'Signal': 'Sinyal',
                'Close': 'Fiyat (USDT)',
                'RSI': 'RSI Değeri',
                'MACD': 'MACD Değeri',
                'ADX': 'ADX Değeri'
            }, inplace=True)

            # Zaman damgasını okunabilir formatta ekle
            display_df['Zaman'] = display_df.index.strftime('%Y-%m-%d %H:%M:%S')

            # Kolon sırasını ayarla
            display_df = display_df[['Zaman', 'Sinyal', 'Fiyat (USDT)', 'RSI Değeri', 'MACD Değeri', 'ADX Değeri']]


            # Sinyale göre satırları renklendirecek fonksiyon
            def style_signals(row):
                color = ''
                if row.Sinyal == 'Al':
                    color = 'background-color: #2a523b; color: white'  # Yeşil tonu
                elif row.Sinyal == 'Sat':
                    color = 'background-color: #602a3a; color: white'  # Kırmızı tonu
                return [color] * len(row)


            # Stilli DataFrame'i göster
            st.dataframe(display_df.style.apply(style_signals, axis=1), use_container_width=True)
        else:
            st.info("Gösterilecek 'Al' veya 'Sat' sinyali bulunamadı.")
        # --- YENİ BÖLÜM SONU ---

    else:
        st.warning(f"{symbol} için veri bulunamadı veya boş.")

# ------------------------------
# Alarmlar ve Telegram Durumu Paneli

st.sidebar.header("🔔 Son Alarmlar")
alarms = get_alarm_history(limit=5)
if alarms is not None and not alarms.empty:
    for idx, row in alarms.iterrows():
        st.sidebar.write(f"{row['timestamp']} - {row['symbol']} - {row['signal']}")
else:
    st.sidebar.write("Henüz alarm yok.")

st.sidebar.markdown("---")
st.sidebar.write(f"🟢 Son Sinyal: {st.session_state.last_signal}")