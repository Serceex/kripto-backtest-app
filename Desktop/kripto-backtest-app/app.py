import streamlit as st
import pandas as pd
import numpy as np
import json
import time
import itertools
import random
import threading

from utils import get_binance_klines, calculate_fibonacci_levels, analyze_backtest_results
from indicators import generate_all_indicators
from features import prepare_features
from ml_model import SignalML
from signals import generate_signals, filter_signals_with_trend, add_higher_timeframe_trend, backtest_signals
from plots import plot_chart, plot_performance_summary
from telegram_alert import send_telegram_message
from alarm_log import log_alarm, get_alarm_history


CONFIG_FILE = "config.json"

def load_config():
    """config.json dosyasından ayarları yükler."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        # Eğer dosya yoksa veya bozuksa, varsayılan bir yapı döndür
        return {
            "live_tracking_enabled": False,
            "telegram_enabled": False,
            "symbols": ["BTCUSDT"],
            "interval": "1h",
            "strategy_params": {}
        }

def save_config(config):
    """Verilen ayarları config.json dosyasına kaydeder."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)


st.set_page_config(page_title="Kripto Portföy Backtest", layout="wide")
st.title("📊 Kripto Portföy Backtest + ML + Optimizasyon + Puzzle Bot")


# Session state'i kullanarak config'i bir kere yükle
if 'config' not in st.session_state:
    st.session_state.config = load_config()

config = st.session_state.config


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

with st.sidebar.expander("⏳ Çoklu Zaman Dilimi Analizi (MTA)", expanded=True):
    use_mta = st.checkbox("Ana Trend Filtresini Kullan", value=True,
                          help="Daha üst bir zaman dilimindeki ana trend yönünde sinyal üretir. Başarı oranını artırır.")
    if use_mta:
        # Mevcut işlem zaman dilimine göre mantıklı bir üst zaman dilimi öner
        timeframe_map = {"15m": "1h", "1h": "4h", "4h": "1d"}
        # 'interval' session_state'de yoksa varsayılan olarak '1h' kullan
        current_interval = st.session_state.get('interval', '1h')
        default_higher_tf = timeframe_map.get(current_interval, "4h")

        higher_tf_options = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]

        # Önerilen üst zaman diliminin index'ini bul, bulamazsa varsayılan olarak 2 (4h) kullan
        try:
            default_index = higher_tf_options.index(default_higher_tf)
        except ValueError:
            default_index = 2

        higher_timeframe = st.selectbox(
            "Ana Trend için Üst Zaman Dilimi",
            options=higher_tf_options,
            index=default_index
        )
        trend_ema_period = st.slider(
            "Trend EMA Periyodu", 20, 200, 50,
            help="Üst zaman diliminde trendi belirlemek için kullanılacak EMA periyodu."
        )
    else:
        higher_timeframe = None
        trend_ema_period = 50


with st.sidebar.expander("🔧 Diğer Parametreler (Genişletmek için tıklayın)", expanded=False):
    st.subheader("🧩 Puzzle Strateji Botu")
    use_puzzle_bot = st.checkbox("Puzzle Strateji Botunu Kullan", value=False, key="puzzle_bot")

    st.subheader("📡 Telegram Bildirimleri")
    use_telegram = st.checkbox("Telegram Bildirimlerini Aç", value=True, key="telegram_alerts")

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
use_bb = col3.checkbox("Bollinger Sinyali", value=False, key='use_bb')
use_adx = col4.checkbox("ADX Sinyali", value=False, key='use_adx')

if use_rsi:
    rsi_period = st.sidebar.number_input("RSI Periyodu", min_value=2, max_value=100, value=14)
    rsi_buy = st.sidebar.slider("RSI Alış Eşiği", min_value=0, max_value=50, value=30, step=1, key="rsi_buy_key")
    rsi_sell = st.sidebar.slider("RSI Satış Eşiği", min_value=50, max_value=100, value=70, step=1, key="rsi_sell_key")
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

adx_threshold = st.sidebar.slider("ADX Eşiği", 10, 50, 25, key="adx_threshold_key")

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

col1, col2, col3 = st.columns(3)

with col1:
    signal_mode = st.selectbox("Sinyal Modu", ["Long Only", "Short Only", "Long & Short"], index=2)
    signal_direction = {"Long Only": "Long", "Short Only": "Short", "Long & Short": "Both"}[signal_mode]

with col2:
    st.subheader("Zarar Durdur (Stop-Loss)")
    sl_type = st.radio("Stop-Loss Türü", ["Yüzde (%)", "ATR"], index=1, horizontal=True, key="sl_type_key")
    if sl_type == "Yüzde (%)":
        stop_loss_pct = st.slider("Stop Loss (%)", 0.0, 10.0, 2.0, step=0.1)
        atr_multiplier = 0 # Kullanılmadığı için 0 yapıyoruz
    else: # ATR Seçiliyse
        atr_multiplier = st.slider("ATR Çarpanı", 1.0, 5.0, 2.0, step=0.1, help="Giriş anındaki ATR değerinin kaç katı uzağa stop konulacağını belirler.", key="atr_multiplier_key")
        stop_loss_pct = 0 # Kullanılmadığı için 0 yapıyoruz

with col3:
    st.subheader("Kâr Al & Bekleme")
    use_trailing_stop = st.checkbox("İz Süren Stop (ATR) Kullan", value=True,
                                    help="Aktifse, sabit Take Profit yerine fiyatı ATR mesafesinden takip eden dinamik bir stop kullanılır. Bu, büyük trendleri yakalamayı hedefler.")

    # Eğer İz Süren Stop kullanılmıyorsa, sabit Take Profit seçeneğini göster
    take_profit_pct = st.slider(
        "Take Profit (%)", 0.0, 20.0, 5.0, step=0.1,
        key="take_profit_pct_key",
        disabled=use_trailing_stop  # Trailing Stop aktifse bunu devre dışı bırak
    )

    cooldown_bars = st.slider("İşlem Arası Bekleme (bar)", 0, 10, 3)

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

    'stop_loss_pct': stop_loss_pct,      # Yüzde SL için bu kalıyor
    'atr_multiplier': atr_multiplier,    # Yeni ATR çarpanını ekliyoruz
    'take_profit_pct': take_profit_pct,
    'cooldown_bars': cooldown_bars,

    'signal_mode': signal_mode,
    'signal_direction': signal_direction,
    'use_puzzle_bot': use_puzzle_bot,
    'use_ml': use_ml,
    'use_mta': use_mta,
    'higher_timeframe': higher_timeframe,
    'trend_ema_period': trend_ema_period,
    'use_trailing_stop': use_trailing_stop
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
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, symbol in enumerate(symbols):
        status_text.text(f"🔍 {symbol} verisi indiriliyor ve strateji uygulanıyor... ({i + 1}/{len(symbols)})")

        # 1. Ana zaman dilimi verisini çek
        df = get_binance_klines(symbol=symbol, interval=interval, limit=1000)
        if df is None or df.empty:
            st.warning(f"{symbol} için ana zaman dilimi ({interval}) verisi alınamadı.")
            continue

        # 2. MTA aktifse, üst zaman dilimi verisini çek
        df_higher = None
        current_use_mta = strategy_params['use_mta']
        if current_use_mta:
            df_higher = get_binance_klines(symbol=symbol, interval=strategy_params['higher_timeframe'], limit=1000)
            if df_higher is None or df_higher.empty:
                st.warning(
                    f"-> {symbol} için üst zaman dilimi ({strategy_params['higher_timeframe']}) verisi alınamadı. Bu sembol için MTA devre dışı.")
                current_use_mta = False  # Sadece bu sembol için MTA'yı kapat

        # 3. Göstergeleri ve ham sinyalleri hesapla
        df = generate_all_indicators(df, **strategy_params)
        df = generate_signals(df, **strategy_params)

        # 4. MTA aktifse, sinyalleri trende göre filtrele
        if current_use_mta and df_higher is not None:
            st.write(f"-> {symbol} için ana trend filtresi uygulanıyor...")
            df = add_higher_timeframe_trend(df, df_higher, strategy_params['trend_ema_period'])
            df = filter_signals_with_trend(df)

    
        # 5. Stop-Loss ve Take-Profit ile backtest yap
        trades = []
        position = None
        entry_price = 0
        entry_time = None
        stop_loss_price = 0  # Pozisyon için dinamik SL fiyatını tutacak
        cooldown = 0

        for k in range(len(df)):
            if cooldown > 0:
                cooldown -= 1
                continue

            current_row = df.iloc[k]
            signal = current_row['Signal']
            price = current_row['Close']
            low_price = current_row['Low']
            high_price = current_row['High']
            time_idx = df.index[k]
            current_atr = current_row.get('ATR', 0)  # ATR yoksa 0 kullan

            # POZİSYON AÇMA MANTIĞI
            if position is None:
                if signal == 'Al' and strategy_params['signal_direction'] != 'Short':
                    position, entry_price, entry_time = 'Long', price, time_idx
                    if strategy_params['atr_multiplier'] > 0 and current_atr > 0:
                        stop_loss_price = price - (current_atr * strategy_params['atr_multiplier'])
                    else:
                        stop_loss_price = price * (1 - strategy_params['stop_loss_pct'] / 100)

                elif signal == 'Sat' and strategy_params['signal_direction'] != 'Long':
                    position, entry_price, entry_time = 'Short', price, time_idx
                    if strategy_params['atr_multiplier'] > 0 and current_atr > 0:
                        stop_loss_price = price + (current_atr * strategy_params['atr_multiplier'])
                    else:
                        stop_loss_price = price * (1 + strategy_params['stop_loss_pct'] / 100)

            # AÇIK POZİSYONU YÖNETME MANTIĞI
            else:
                exit_condition = False

                # --- YENİ İZ SÜREN STOP MANTIĞI ---
                if strategy_params.get('use_trailing_stop', False) and current_atr > 0:
                    if position == 'Long':
                        new_stop_price = high_price - (current_atr * strategy_params['atr_multiplier'])
                        # Stop'u sadece yukarı taşı
                        if new_stop_price > stop_loss_price:
                            stop_loss_price = new_stop_price
                    elif position == 'Short':
                        new_stop_price = low_price + (current_atr * strategy_params['atr_multiplier'])
                        # Stop'u sadece aşağı taşı
                        if new_stop_price < stop_loss_price:
                            stop_loss_price = new_stop_price
                # --- İZ SÜREN STOP MANTIĞI SONU ---

                # Take Profit kontrolü (sadece İz Süren Stop kapalıysa çalışır)
                tp_triggered = False
                if not strategy_params.get('use_trailing_stop', False) and strategy_params['take_profit_pct'] > 0:
                    ret = ((price - entry_price) / entry_price * 100) if position == 'Long' else (
                                (entry_price - price) / entry_price * 100)
                    if ret >= strategy_params['take_profit_pct']:
                        tp_triggered = True

                # Çıkış koşullarını kontrol et
                if position == 'Long':
                    if low_price <= stop_loss_price or signal == 'Sat' or tp_triggered:
                        exit_condition = True
                elif position == 'Short':
                    if high_price >= stop_loss_price or signal == 'Al' or tp_triggered:
                        exit_condition = True

                if exit_condition:
                    exit_price = price
                    if position == 'Long' and low_price <= stop_loss_price: exit_price = stop_loss_price
                    if position == 'Short' and high_price >= stop_loss_price: exit_price = stop_loss_price

                    ret = ((exit_price - entry_price) / entry_price * 100) if position == 'Long' else (
                                (entry_price - exit_price) / entry_price * 100)

                    trades.append({
                        'Pozisyon': position, 'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                        'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': exit_price, 'Getiri (%)': round(ret, 2)
                    })
                    position, cooldown = None, strategy_params['cooldown_bars']

        if trades:
            trades_df = pd.DataFrame(trades)
            trades_df['Sembol'] = symbol
            all_results.append(trades_df)

        st.session_state.backtest_data[symbol] = df
        progress_bar.progress((i + 1) / len(symbols))

    status_text.success("🚀 Backtest tamamlandı!")

    if all_results:
        portfolio_results = pd.concat(all_results, ignore_index=True).sort_values("Giriş Zamanı")
        st.session_state['backtest_results'] = portfolio_results
    else:
        st.session_state['backtest_results'] = pd.DataFrame()

def apply_selected_params(selected_params):
        """
        Seçilen optimizasyon parametrelerini session_state'e uygular.
        Bu fonksiyon, butonun on_click olayı ile tetiklenir.
        """
        st.session_state.rsi_buy_key = int(selected_params['rsi_buy'])
        st.session_state.rsi_sell_key = int(selected_params['rsi_sell'])
        st.session_state.adx_threshold_key = int(selected_params['adx_threshold'])
        st.session_state.atr_multiplier_key = float(selected_params['atr_multiplier'])
        st.session_state.take_profit_pct_key = float(selected_params['take_profit_pct'])
        st.session_state.sl_type_key = "ATR"
        st.success("Parametreler başarıyla uygulandı! Ayarlar kenar çubuğuna aktarıldı.")


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
        portfolio_results = st.session_state['backtest_results'].copy()

        # 'Çıkış Zamanı' NaT olanları (açık pozisyonları) analizden çıkar
        analysis_df = portfolio_results.dropna(subset=['Çıkış Zamanı'])

        if not analysis_df.empty:
            # Yeni analiz fonksiyonunu çağır (artık 3 değer döndürüyor)
            performance_metrics, equity_curve, drawdown_series = analyze_backtest_results(analysis_df)

            st.subheader("📊 Portföy Performans Metrikleri")

        metric_tooltips = {
            "Toplam İşlem": "Backtest süresince yapılan toplam alım-satım işlemi sayısı.",
            "Kazançlı İşlem Oranı (%)": "Toplam işlemlerin yüzde kaçının kâr ile sonuçlandığı.",
            "Toplam Getiri (%)": "Tüm işlemlerden elde edilen net kâr/zarar yüzdesi. (Sadece işlem getirileri, bileşik değil)",
            "Ortalama Kazanç (%)": "Sadece kârlı işlemlerin ortalama getiri yüzdesi.",
            "Ortalama Kayıp (%)": "Sadece zararlı işlemlerin ortalama getiri yüzdesi.",
            "Risk/Ödül Oranı (Payoff)": "Ortalama kazancın ortalama kayba oranı. 1'den büyük olması istenir.",
            "Maksimum Düşüş (Drawdown) (%)": "Stratejinin geçmişte yaşadığı en büyük tepeden-dibe sermaye erimesi yüzdesi. Stratejinin potansiyel riskini gösterir.",
            "Sharpe Oranı (Yıllık)": "Stratejinin aldığı riske (volatiliteye) göre ne kadar getiri ürettiğini ölçer. Yüksek olması daha verimlidir.",
            "Sortino Oranı (Yıllık)": "Sharpe Oranı'na benzer, ancak sadece aşağı yönlü (negatif) riski dikkate alır. Trader'lar için daha anlamlı olabilir.",
            "Calmar Oranı": "Yıllıklandırılmış getirinin maksimum düşüşe oranıdır. Stratejinin getirisinin, yaşadığı en kötü düşüşe göre ne kadar iyi olduğunu gösterir."
        }

        col1, col2 = st.columns(2)
        metrics_list = list(performance_metrics.items())
        mid_point = (len(metrics_list) + 1) // 2

        with col1:
            for key, value in metrics_list[:mid_point]:
                st.metric(label=key, value=value, help=metric_tooltips.get(key, ""))
        with col2:
            for key, value in metrics_list[mid_point:]:
                st.metric(label=key, value=value, help=metric_tooltips.get(key, ""))

        # --- YENİ EKLENEN BÖLÜM: PERFORMANS GRAFİĞİ ---
        st.subheader("📈 Strateji Performans Grafiği")
        if equity_curve is not None and drawdown_series is not None:
            performance_fig = plot_performance_summary(equity_curve, drawdown_series)
            st.plotly_chart(performance_fig, use_container_width=True)
        # --- GRAFİK BÖLÜMÜ SONU ---

        st.subheader("📋 Tüm İşlemler")
        st.dataframe(portfolio_results)
    else:
        st.info("Backtest sonuçları burada görünecek. Lütfen 'Portföy Backtest Başlat' butonuna basın.")

elif page == "Canlı İzleme":
    st.header("📡 Canlı Sinyal İzleme")

    st.info("""
    Bu sayfa, arka planda çalışan `worker.py` script'ini kontrol eder. 
    Worker'ı başlatmak için terminalde `python worker.py` komutunu çalıştırdığınızdan emin olun.
    """)

    # Worker'ın durumunu config dosyasından oku
    is_worker_running = config.get("live_tracking_enabled", False)
    status_color = "green" if is_worker_running else "red"
    status_text = "AKTİF" if is_worker_running else "DURDURULDU"

    st.markdown(f"**Worker Durumu:** <font color='{status_color}'>{status_text}</font>", unsafe_allow_html=True)
    st.markdown(f"**Takip Edilen Semboller:** `{', '.join(config.get('symbols', []))}`")
    st.markdown(f"**Zaman Dilimi:** `{config.get('interval')}`")

    col1, col2 = st.columns(2)

    if col1.button("▶️ Canlı İzlemeyi Başlat/Güncelle"):
        # Arayüzdeki güncel ayarları config dosyasına yaz
        config["live_tracking_enabled"] = True
        config["telegram_enabled"] = use_telegram
        config["symbols"] = symbols
        config["interval"] = interval
        config["strategy_params"] = strategy_params
        save_config(config)
        st.session_state.config = config  # Session state'i de güncelle
        st.success("Worker'a 'BAŞLAT' komutu gönderildi. Ayarlar güncellendi.")
        st.rerun()

    if col2.button("⏹️ Canlı İzlemeyi Durdur"):
        config["live_tracking_enabled"] = False
        save_config(config)
        st.session_state.config = config  # Session state'i de güncelle
        st.warning("Worker'a 'DURDUR' komutu gönderildi.")
        st.rerun()

    st.subheader("🔔 Son Alarmlar (Worker Tarafından Üretilen)")
    alarm_history = get_alarm_history(limit=10)  # alarm_log.py'dan fonksiyon
    if alarm_history is not None and not alarm_history.empty:
        st.dataframe(alarm_history, use_container_width=True)
    else:
        st.info("Henüz worker tarafından üretilmiş bir alarm yok veya `alarm_history.csv` bulunamadı.")



# app.py dosyasında, mevcut 'elif page == "Optimizasyon":' bloğunu silip yerine bunu yapıştırın.

elif page == "Optimizasyon":
    st.header("⚙️ Strateji Parametre Optimizasyonu")
    st.info("""
    Bu bölümde, stratejinizin en iyi performans gösteren parametrelerini bulmak için binlerce kombinasyonu test edebilirsiniz.
    Lütfen optimize etmek istediğiniz hedefi ve parametrelerin test edileceği aralıkları seçin.
    """)

    # --- Optimizasyon Hedefi ---
    st.subheader("1. Optimizasyon Hedefini Seçin")
    optimization_target = st.selectbox(
        "Hangi Metriğe Göre Optimize Edilsin?",
        options=["Sharpe Oranı (Yıllık)", "Sortino Oranı (Yıllık)", "Calmar Oranı", "Maksimum Düşüş (Drawdown) (%)",
                 "Toplam Getiri (%)"],
        index=0,
        help="Optimizasyon, seçtiğiniz bu metriği maksimize (veya Drawdown için minimize) etmeye çalışacaktır."
    )

    # --- Parametre Aralıkları ---
    st.subheader("2. Parametre Test Aralıklarını Belirleyin")

    param_col1, param_col2 = st.columns(2)

    with param_col1:
        st.write("Sinyal Parametreleri")
        rsi_buy_range = st.slider("RSI Alış Eşiği Aralığı", 0, 50, (25, 35))
        rsi_sell_range = st.slider("RSI Satış Eşiği Aralığı", 50, 100, (65, 75))
        adx_thresh_range = st.slider("ADX Eşiği Aralığı", 10, 50, (20, 30))

    with param_col2:
        st.write("Risk Yönetimi Parametreleri")
        atr_multiplier_range = st.slider("ATR Çarpanı Aralığı", 1.0, 5.0, (1.5, 2.5))
        tp_pct_range = st.slider("Take Profit (%) Aralığı", 1.0, 20.0, (4.0, 8.0))

    # --- Optimizasyon Kontrolü ---
    st.subheader("3. Optimizasyonu Başlatın")

    total_combinations = (
            len(range(rsi_buy_range[0], rsi_buy_range[1] + 1, 5)) *
            len(range(rsi_sell_range[0], rsi_sell_range[1] + 1, 5)) *
            len(range(adx_thresh_range[0], adx_thresh_range[1] + 1, 5)) *
            len([round(x * 0.5, 1) for x in
                 range(int(atr_multiplier_range[0] * 2), int(atr_multiplier_range[1] * 2) + 1)]) *
            len([round(x * 1.0, 1) for x in range(int(tp_pct_range[0]), int(tp_pct_range[1]) + 1)])
    )
    st.write(f"Tahmini Test Kombinasyon Sayısı: **{total_combinations}**")

    max_tests = st.slider("Maksimum Test Sayısı", 5, 1000, 200,
                          help="Eğer toplam kombinasyon çok fazlaysa, testler bu sayıdaki rastgele örneklem üzerinden yapılır.")

    if st.button("🚀 Optimizasyonu Başlat", type="primary"):

        # Parametre grid'ini oluştur
        param_grid = {
            'rsi_buy': range(rsi_buy_range[0], rsi_buy_range[1] + 1, 5),
            'rsi_sell': range(rsi_sell_range[0], rsi_sell_range[1] + 1, 5),
            'adx_threshold': range(adx_thresh_range[0], adx_thresh_range[1] + 1, 5),
            'atr_multiplier': [round(x * 0.5, 1) for x in
                               range(int(atr_multiplier_range[0] * 2), int(atr_multiplier_range[1] * 2) + 1)],
            'take_profit_pct': [round(x * 1.0, 1) for x in range(int(tp_pct_range[0]), int(tp_pct_range[1]) + 1)]
        }

        keys, values = zip(*param_grid.items())
        all_combinations = [dict(zip(keys, v)) for v in itertools.product(*values)]

        if len(all_combinations) > max_tests:
            st.warning(f"{len(all_combinations)} kombinasyon bulundu. Rastgele {max_tests} tanesi test ediliyor...")
            test_combinations = random.sample(all_combinations, max_tests)
        else:
            test_combinations = all_combinations

        results_list = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, params_to_test in enumerate(test_combinations):
            # Ana backtest'teki parametreleri kopyala ve bu iterasyon için olanlarla güncelle
            current_params = strategy_params.copy()
            current_params.update(params_to_test)

            # ATR stop kullanıldığını varsay, yüzdeyi sıfırla
            current_params['stop_loss_pct'] = 0

            all_trades = []
            for symbol in symbols:
                df = get_binance_klines(symbol=symbol, interval=interval, limit=1000)
                if df is None or df.empty: continue

                df = generate_all_indicators(df, **current_params)
                df = generate_signals(df, **current_params)

                # MTA filtresini uygula
                if current_params['use_mta']:
                    df_higher = get_binance_klines(symbol, current_params['higher_timeframe'], 1000)
                    if df_higher is not None and not df_higher.empty:
                        df = add_higher_timeframe_trend(df, df_higher, current_params['trend_ema_period'])
                        df = filter_signals_with_trend(df)

                trades_df = backtest_signals(df)  # Basit backtest yeterli
                if not trades_df.empty:
                    all_trades.append(trades_df)

            if all_trades:
                final_trades = pd.concat(all_trades, ignore_index=True).dropna(subset=['Çıkış Zamanı'])
                if not final_trades.empty:
                    metrics, _, _ = analyze_backtest_results(final_trades)
                    # Parametreleri ve metrikleri birleştir
                    result_row = params_to_test.copy()
                    # Metriklerdeki "%" ve string ifadeleri temizleyip float'a çevir
                    for key, val in metrics.items():
                        try:
                            result_row[key] = float(str(val).replace('%', ''))
                        except (ValueError, TypeError):
                            result_row[key] = val
                    results_list.append(result_row)

            progress_bar.progress((i + 1) / len(test_combinations))
            status_text.text(
                f"Test {i + 1}/{len(test_combinations)} tamamlandı. En iyi {optimization_target}: {st.session_state.get('best_score', 'N/A')}")

        if results_list:
            results_df = pd.DataFrame(results_list)

            # Hedefe göre sırala
            is_ascending = True if optimization_target == "Maksimum Düşüş (Drawdown) (%)" else False
            sorted_results = results_df.sort_values(by=optimization_target, ascending=is_ascending).head(10)

            st.session_state.best_score = f"{sorted_results.iloc[0][optimization_target]:.2f}"
            st.session_state.optimization_results = sorted_results

        status_text.success("✅ Optimizasyon tamamlandı! En iyi 10 sonuç aşağıda listelenmiştir.")

    # app.py dosyasındaki 'elif page == "Optimizasyon":' bloğunun sonundaki
    # 'if 'optimization_results' in st.session_state:' koşulunu bununla değiştirin.

    if 'optimization_results' in st.session_state and not st.session_state.optimization_results.empty:
        st.subheader("🏆 En İyi Parametre Kombinasyonları")
        results_df = st.session_state.optimization_results

        # Görüntüleme için gereksiz kolonları kaldır
        display_cols = [
            'rsi_buy', 'rsi_sell', 'adx_threshold', 'atr_multiplier', 'take_profit_pct',
            optimization_target, 'Toplam İşlem', 'Kazançlı İşlem Oranı (%)'
        ]
        # Sadece var olan kolonları göster
        display_cols_exist = [col for col in display_cols if col in results_df.columns]
        st.dataframe(results_df[display_cols_exist])

        # --- GÜNCELLENMİŞ "UYGULA" BÖLÜMÜ ---
        st.subheader("4. Sonuçları Kenar Çubuğuna Aktar")

        selected_index = st.selectbox(
            "Uygulamak istediğiniz sonucun index'ini seçin:",
            results_df.index,
            help="Yukarıdaki tablodan en beğendiğiniz sonucun index numarasını seçin."
        )

        # Butona tıklandığında çalışacak callback fonksiyonunu ve argümanlarını ata
        st.button(
            "✅ Seçili Parametreleri Uygula",
            on_click=apply_selected_params,
            args=(results_df.loc[selected_index],)  # args'ı bir tuple olarak göndermeyi unutmayın (sonunda virgül var)
        )

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