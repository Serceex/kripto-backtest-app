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
from database import (
    add_or_update_strategy, remove_strategy,
    get_all_strategies, initialize_db, get_alarm_history_db)


def apply_full_strategy_params(strategy):
    """
    Seçilen bir stratejinin tüm parametrelerini session_state'e uygular,
    böylece kenar çubuğu yeniden yüklendiğinde bu değerlerle başlar.
    """
    params = strategy.get('strategy_params', {})
    strategy_name = strategy.get('name', 'İsimsiz Strateji')

    # Kenar Çubuğu -> Sinyal Kriterleri
    st.session_state.use_rsi = params.get('use_rsi', True)
    st.session_state.rsi_period = params.get('rsi_period', 14)
    st.session_state.rsi_buy_key = params.get('rsi_buy', 30)
    st.session_state.rsi_sell_key = params.get('rsi_sell', 70)

    st.session_state.use_macd = params.get('use_macd', True)
    st.session_state.macd_fast = params.get('macd_fast', 12)
    st.session_state.macd_slow = params.get('macd_slow', 26)
    st.session_state.macd_signal = params.get('macd_signal', 9)

    st.session_state.use_bb = params.get('use_bb', False)
    st.session_state.bb_period = params.get('bb_period', 20)
    st.session_state.bb_std = params.get('bb_std', 2.0)

    st.session_state.use_adx = params.get('use_adx', False)
    st.session_state.adx_threshold_key = params.get('adx_threshold', 25)

    # Expander -> Strateji Gelişmiş Ayarlar
    direction_map = {"Long": "Long Only", "Short": "Short Only", "Both": "Long & Short"}
    st.session_state.signal_mode_key = direction_map.get(params.get('signal_direction', 'Both'), "Long & Short")
    st.session_state.signal_logic_key = "AND (Teyitli)" if params.get('signal_mode') == 'and' else "OR (Hızlı)"
    st.session_state.cooldown_bars_key = params.get('cooldown_bars', 3)

    # Stop-Loss
    if params.get('atr_multiplier', 0) > 0:
        st.session_state.sl_type_key = "ATR"
        st.session_state.atr_multiplier_key = params.get('atr_multiplier', 2.0)
    else:
        st.session_state.sl_type_key = "Yüzde (%)"
        st.session_state.stop_loss_pct_key = params.get('stop_loss_pct', 2.0)

    # Take-Profit & Komisyon
    st.session_state.trailing_stop_key = params.get('use_trailing_stop', True)
    st.session_state.take_profit_pct_key = params.get('take_profit_pct', 5.0)
    st.session_state.commission_pct_key = params.get('commission_pct', 0.1)

    # Expander -> MTA
    st.session_state.use_mta_key = params.get('use_mta', True)
    st.session_state.higher_timeframe_key = params.get('higher_timeframe', '4h')
    st.session_state.trend_ema_period_key = params.get('trend_ema_period', 50)

    # Expander -> Diğer Parametreler
    st.session_state.puzzle_bot = params.get('use_puzzle_bot', False)
    st.session_state.ml_toggle = params.get('use_ml', False)

    st.toast(f"'{strategy_name}' stratejisinin parametreleri yüklendi!", icon="✅")



initialize_db()

# Kullanıcının giriş durumunu saklamak için session_state'i başlat
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False


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


st.set_page_config(page_title="Veritas Point Labs", layout="wide")
st.title("📊 Veritas Point Labs")


# Session state'i kullanarak config'i bir kere yükle
if 'config' not in st.session_state:
    st.session_state.config = load_config()

config = st.session_state.config


st.sidebar.header("🔎 Sayfa Seçimi")
page = st.sidebar.radio(
    "Sayfa",
    ["Portföy Backtest", "Detaylı Grafik Analizi", "Canlı İzleme", "Optimizasyon"]
)


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

# --- YENİ ve KÜÇÜLTÜLMÜŞ HALİ ---

with st.expander("⚙️ Strateji Gelişmiş Ayarlar", expanded=False):
    col1, col2, col3 = st.columns(3)

    with col1:

        signal_mode = st.selectbox("Sinyal Modu", ["Long Only", "Short Only", "Long & Short"], index=2,
                                   key="signal_mode_key")
        signal_direction = {"Long Only": "Long", "Short Only": "Short", "Long & Short": "Both"}[signal_mode]

        signal_logic = st.selectbox("Sinyal Mantığı", ["AND (Teyitli)", "OR (Hızlı)"], index=0,
                                    help="AND: Tüm aktif göstergeler aynı anda sinyal vermeli. OR: Herhangi bir göstergenin sinyali yeterli.")

        #st.subheader("İşlem Arası Bekleme")
        st.markdown("**İşlem Arası Bekleme**")
        cooldown_bars = st.slider("Bekleme (bar)", 0, 10, 3, key="cooldown_bars_key", label_visibility="collapsed")

    with col2:
        st.markdown("**Zarar Durdur (Stop-Loss)**")
        sl_type = st.radio("Stop-Loss Türü", ["Yüzde (%)", "ATR"], index=1, horizontal=True, key="sl_type_key")
        if sl_type == "Yüzde (%)":
            stop_loss_pct = st.slider("Stop Loss (%)", 0.0, 10.0, 2.0, step=0.1)
            atr_multiplier = 0
        else:  # ATR Seçiliyse
            atr_multiplier = st.slider("ATR Çarpanı", 1.0, 5.0, 2.0, step=0.1,
                                       help="Giriş anındaki ATR değerinin kaç katı uzağa stop konulacağını belirler.",
                                       key="atr_multiplier_key")
            stop_loss_pct = 0

    with col3:
        st.markdown("**Kâr Al & Maliyet**")
        use_trailing_stop = st.checkbox("İz Süren Stop (ATR) Kullan", value=True,
                                        help="Aktifse, sabit Take Profit yerine fiyatı ATR mesafesinden takip eden dinamik bir stop kullanılır.",
                                        key="trailing_stop_key")

        take_profit_pct = st.slider(
            "Take Profit (%)", 0.0, 20.0, 5.0, step=0.1,
            key="take_profit_pct_key",
            disabled=use_trailing_stop
        )

        commission_pct = st.slider(
            "İşlem Başına Komisyon (%)", 0.0, 0.5, 0.1, step=0.01,
            key="commission_pct_key",
            help="Her alım veya satım işlemi için ödenecek komisyon oranı. Binance için genellikle %0.1'dir."
        )



strategy_params = {
    'sma': sma_period, 'ema': ema_period, 'bb_period': bb_period, 'bb_std': bb_std, 'rsi_buy': rsi_buy,
    'rsi_sell': rsi_sell, 'rsi_period': rsi_period, 'macd_fast': macd_fast, 'macd_slow': macd_slow,
    'macd_signal': macd_signal, 'adx_period': 14, 'adx_threshold': adx_threshold, 'use_rsi': use_rsi,
    'use_macd': use_macd, 'use_bb': use_bb, 'use_adx': use_adx, 'stop_loss_pct': stop_loss_pct,
    'atr_multiplier': atr_multiplier, 'take_profit_pct': take_profit_pct, 'cooldown_bars': cooldown_bars,
    'signal_mode': 'and' if signal_logic == "AND (Teyitli)" else 'or',
    'signal_direction': {"Long Only": "Long", "Short Only": "Short", "Long & Short": "Both"}[signal_mode],
    'use_puzzle_bot': use_puzzle_bot, 'use_ml': use_ml, 'use_mta': use_mta,
    'higher_timeframe': higher_timeframe, 'trend_ema_period': trend_ema_period,
    'commission_pct': commission_pct, 'use_trailing_stop': use_trailing_stop
}

if "live_running" not in st.session_state: st.session_state.live_running = False
if "live_thread_started" not in st.session_state: st.session_state.live_thread_started = False
if "last_signal" not in st.session_state: st.session_state.last_signal = "Henüz sinyal yok."
if "backtest_results" not in st.session_state: st.session_state.backtest_results = pd.DataFrame()


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


# app.py dosyasındaki ESKİ run_portfolio_backtest fonksiyonunun yerine bunu yapıştırın.

def run_portfolio_backtest(symbols, interval, strategy_params):
    """
    "Geleceği Görme" (Lookahead Bias) hatası giderilmiş, gerçekçi backtest fonksiyonu.
    """
    all_results = []
    st.session_state.backtest_data = {}
    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, symbol in enumerate(symbols):
        status_text.text(f"🔍 {symbol} verisi indiriliyor ve strateji uygulanıyor... ({i + 1}/{len(symbols)})")
        df = get_binance_klines(symbol=symbol, interval=interval, limit=1000)
        if df is None or df.empty:
            st.warning(f"{symbol} için veri alınamadı.")
            continue

        df_higher, current_use_mta = None, strategy_params['use_mta']
        if current_use_mta:
            df_higher = get_binance_klines(symbol=symbol, interval=strategy_params['higher_timeframe'], limit=1000)
            if df_higher is None or df_higher.empty: current_use_mta = False

        df = generate_all_indicators(df, **strategy_params)
        df = generate_signals(df, **strategy_params)

        if current_use_mta and df_higher is not None:
            df = add_higher_timeframe_trend(df, df_higher, strategy_params['trend_ema_period'])
            df = filter_signals_with_trend(df)

        trades, position, entry_price, entry_time, stop_loss_price, cooldown = [], None, 0, None, 0, 0
        for k in range(1, len(df)):
            if cooldown > 0:
                cooldown -= 1
                continue
            prev_row, current_row = df.iloc[k - 1], df.iloc[k]
            signal, open_price, low_price, high_price = prev_row['Signal'], current_row['Open'], current_row['Low'], \
            current_row['High']
            time_idx, current_atr = current_row.name, prev_row.get('ATR', 0)

            if position is not None:
                exit_price = None
                if strategy_params.get('use_trailing_stop', False) and current_atr > 0:
                    if position == 'Long':
                        new_stop_price = high_price - (current_atr * strategy_params['atr_multiplier'])
                        if new_stop_price > stop_loss_price: stop_loss_price = new_stop_price
                    elif position == 'Short':
                        new_stop_price = low_price + (current_atr * strategy_params['atr_multiplier'])
                        if new_stop_price < stop_loss_price: stop_loss_price = new_stop_price
                if position == 'Long':
                    if low_price <= stop_loss_price:
                        exit_price = stop_loss_price
                    elif not strategy_params.get('use_trailing_stop', False) and high_price >= entry_price * (
                            1 + strategy_params['take_profit_pct'] / 100):
                        exit_price = entry_price * (1 + strategy_params['take_profit_pct'] / 100)
                    elif signal == 'Short' or signal == 'Sat':
                        exit_price = open_price
                elif position == 'Short':
                    if high_price >= stop_loss_price:
                        exit_price = stop_loss_price
                    elif not strategy_params.get('use_trailing_stop', False) and low_price <= entry_price * (
                            1 - strategy_params['take_profit_pct'] / 100):
                        exit_price = entry_price * (1 - strategy_params['take_profit_pct'] / 100)
                    elif signal == 'Al':
                        exit_price = open_price

                if exit_price is not None:
                    gross_ret = ((exit_price - entry_price) / entry_price * 100) if position == 'Long' else (
                                (entry_price - exit_price) / entry_price * 100)
                    ret = gross_ret - (strategy_params['commission_pct'] * 2)
                    trades.append({'Pozisyon': position, 'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                                   'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': exit_price,
                                   'Getiri (%)': round(ret, 2)})
                    position, cooldown = None, strategy_params['cooldown_bars']

            if position is None:
                if signal == 'Al' and strategy_params['signal_direction'] != 'Short':
                    position, entry_price, entry_time = 'Long', open_price, time_idx
                    stop_loss_price = entry_price - (current_atr * strategy_params['atr_multiplier']) if \
                    strategy_params['atr_multiplier'] > 0 and current_atr > 0 else entry_price * (
                                1 - strategy_params['stop_loss_pct'] / 100)
                elif signal == 'Short' and strategy_params['signal_direction'] != 'Long':
                    position, entry_price, entry_time = 'Short', open_price, time_idx
                    stop_loss_price = entry_price + (current_atr * strategy_params['atr_multiplier']) if \
                    strategy_params['atr_multiplier'] > 0 and current_atr > 0 else entry_price * (
                                1 + strategy_params['stop_loss_pct'] / 100)

        if trades:
            trades_df = pd.DataFrame(trades)
            trades_df['Sembol'] = symbol
            all_results.append(trades_df)
        st.session_state.backtest_data[symbol] = df
        progress_bar.progress((i + 1) / len(symbols))

    status_text.success("🚀 Backtest tamamlandı!")
    if all_results:
        st.session_state['backtest_results'] = pd.concat(all_results, ignore_index=True).sort_values("Giriş Zamanı")
    else:
        st.session_state['backtest_results'] = pd.DataFrame()

def apply_selected_params(selected_params):
            st.session_state.rsi_buy_key = int(selected_params['rsi_buy'])
            st.session_state.rsi_sell_key = int(selected_params['rsi_sell'])
            st.session_state.adx_threshold_key = int(selected_params['adx_threshold'])
            st.session_state.atr_multiplier_key = float(selected_params['atr_multiplier'])
            st.session_state.take_profit_pct_key = float(selected_params['take_profit_pct'])
            st.session_state.sl_type_key = "ATR"
            st.success("Parametreler başarıyla uygulandı! Ayarlar kenar çubuğuna aktarıldı.")


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


# app.py dosyasındaki ESKİ run_portfolio_optimization fonksiyonunu silip yerine bunu yapıştırın.

def run_portfolio_optimization(symbols, interval, strategy_params):
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
    # ... (Kombinasyon hesaplama kodları aynı kalabilir)

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

        # ... (Örneklem seçme kodları aynı kalabilir)
        max_tests = 200  # Örnek olarak
        if len(all_combinations) > max_tests:
            test_combinations = random.sample(all_combinations, max_tests)
        else:
            test_combinations = all_combinations

        results_list = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        for i, params_to_test in enumerate(test_combinations):
            current_params = strategy_params.copy()
            current_params.update(params_to_test)
            current_params['stop_loss_pct'] = 0  # ATR kullandığımız için yüzdeyi sıfırla

            all_trades = []
            for symbol in symbols:
                df = get_binance_klines(symbol=symbol, interval=interval, limit=1000)
                if df is None or df.empty: continue

                df = generate_all_indicators(df, **current_params)
                df = generate_signals(df, **current_params)
                if current_params['use_mta']:
                    df_higher = get_binance_klines(symbol, current_params['higher_timeframe'], 1000)
                    if df_higher is not None and not df_higher.empty:
                        df = add_higher_timeframe_trend(df, df_higher, current_params['trend_ema_period'])
                        df = filter_signals_with_trend(df)

                # --- BURADAN İTİBAREN YENİ BACKTEST DÖNGÜSÜ ---
                trades = []
                position = None
                entry_price = 0
                entry_time = None
                stop_loss_price = 0
                cooldown = 0

                for k in range(1, len(df)):
                    if cooldown > 0:
                        cooldown -= 1
                        continue

                    prev_row = df.iloc[k - 1]
                    current_row = df.iloc[k]

                    signal = prev_row['Signal']
                    open_price = current_row['Open']
                    low_price = current_row['Low']
                    high_price = current_row['High']
                    time_idx = current_row.name
                    current_atr = prev_row.get('ATR', 0)

                    if position is not None:
                        exit_price = None
                        if current_params.get('use_trailing_stop', False) and current_atr > 0:
                            if position == 'Long':
                                new_stop_price = high_price - (current_atr * current_params['atr_multiplier'])
                                if new_stop_price > stop_loss_price: stop_loss_price = new_stop_price
                            elif position == 'Short':
                                new_stop_price = low_price + (current_atr * current_params['atr_multiplier'])
                                if new_stop_price < stop_loss_price: stop_loss_price = new_stop_price

                        if position == 'Long':
                            if low_price <= stop_loss_price:
                                exit_price = stop_loss_price
                            elif not current_params.get('use_trailing_stop', False) and high_price >= entry_price * (
                                    1 + current_params['take_profit_pct'] / 100):
                                exit_price = entry_price * (1 + current_params['take_profit_pct'] / 100)
                            elif signal == 'Sat':
                                exit_price = open_price

                        elif position == 'Short':
                            if high_price >= stop_loss_price:
                                exit_price = stop_loss_price
                            elif not current_params.get('use_trailing_stop', False) and low_price <= entry_price * (
                                    1 - current_params['take_profit_pct'] / 100):
                                exit_price = entry_price * (1 - current_params['take_profit_pct'] / 100)
                            elif signal == 'Al':
                                exit_price = open_price

                        if exit_price is not None:
                            # Brüt getiriyi hesapla
                            gross_ret = ((exit_price - entry_price) / entry_price * 100) if position == 'Long' else (
                                        (entry_price - exit_price) / entry_price * 100)

                            # Komisyonu düşerek net getiriyi hesapla
                            commission_cost = current_params['commission_pct'] * 2
                            ret = gross_ret - commission_cost

                            trades.append({'Pozisyon': position, 'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                                           'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': exit_price,
                                           'Getiri (%)': round(ret, 2)})
                            position, cooldown = None, current_params['cooldown_bars']

                    if position is None:
                        if signal == 'Al' and current_params['signal_direction'] != 'Short':
                            position, entry_price, entry_time = 'Long', open_price, time_idx
                            if current_params['atr_multiplier'] > 0 and current_atr > 0:
                                stop_loss_price = entry_price - (current_atr * current_params['atr_multiplier'])
                        elif signal == 'Sat' and current_params['signal_direction'] != 'Long':
                            position, entry_price, entry_time = 'Short', open_price, time_idx
                            if current_params['atr_multiplier'] > 0 and current_atr > 0:
                                stop_loss_price = entry_price + (current_atr * current_params['atr_multiplier'])
                # --- YENİ DÖNGÜ SONU ---

                if trades:
                    trades_df = pd.DataFrame(trades)
                    all_trades.append(trades_df)

            if all_trades:
                final_trades = pd.concat(all_trades, ignore_index=True).dropna(subset=['Çıkış Zamanı'])
                if not final_trades.empty:
                    metrics, _, _ = analyze_backtest_results(final_trades)
                    result_row = params_to_test.copy()
                    for key, val in metrics.items():
                        try:
                            result_row[key] = float(str(val).replace('%', ''))
                        except (ValueError, TypeError):
                            result_row[key] = val
                    results_list.append(result_row)

            progress_bar.progress((i + 1) / len(test_combinations))
            status_text.text(f"Test {i + 1}/{len(test_combinations)} tamamlandı.")

        if results_list:
            results_df = pd.DataFrame(results_list)
            is_ascending = True if optimization_target == "Maksimum Düşüş (Drawdown) (%)" else False
            sorted_results = results_df.sort_values(by=optimization_target, ascending=is_ascending).head(10)
            st.session_state.optimization_results = sorted_results

        status_text.success("✅ Optimizasyon tamamlandı!")


# ------------------------------
# Ana Sayfa Menü Yönetimi

if page == "Portföy Backtest":


    # Seçilen sembolleri session_state'e kaydet (opsiyonel ama iyi bir pratik)
    st.session_state.selected_symbols = symbols

    if st.button("🚀 Portföy Backtest Başlat"):
        # run_portfolio_backtest fonksiyonu, sonuçları st.session_state['backtest_results']'e kaydeder
        run_portfolio_backtest(symbols, interval, strategy_params)

    # Backtest sonuçları varsa, sonuçları göster
    if 'backtest_results' in st.session_state and not st.session_state['backtest_results'].empty:
        portfolio_results = st.session_state['backtest_results'].copy()

        # Analiz için 'Çıkış Zamanı' olmayan (açık) pozisyonları çıkar
        analysis_df = portfolio_results.dropna(subset=['Çıkış Zamanı'])

        if not analysis_df.empty:
            # Analiz fonksiyonu 3 değer döndürür: metrikler, sermaye eğrisi, düşüş serisi
            performance_metrics, equity_curve, drawdown_series = analyze_backtest_results(analysis_df)

            st.subheader("📊 Portföy Performans Metrikleri")

            # Metrikleri ve açıklamalarını tanımla
            metric_tooltips = {
                "Toplam İşlem": "Backtest süresince yapılan toplam alım-satım işlemi sayısı.",
                "Kazançlı İşlem Oranı (%)": "Toplam işlemlerin yüzde kaçının kâr ile sonuçlandığı.",
                "Toplam Getiri (%)": "Tüm işlemlerden elde edilen net kâr/zarar yüzdesi.",
                "Ortalama Kazanç (%)": "Sadece kârlı işlemlerin ortalama getiri yüzdesi.",
                "Ortalama Kayıp (%)": "Sadece zararlı işlemlerin ortalama getiri yüzdesi.",
                "Risk/Ödül Oranı (Payoff)": "Ortalama kazancın ortalama kayba oranı. 1'den büyük olması istenir.",
                "Maksimum Düşüş (Drawdown) (%)": "Stratejinin geçmişte yaşadığı en büyük tepeden-dibe sermaye erimesi yüzdesi.",
                "Sharpe Oranı (Yıllık)": "Stratejinin aldığı riske (volatiliteye) göre ne kadar getiri ürettiğini ölçer.",
                "Sortino Oranı (Yıllık)": "Sharpe Oranı'na benzer, ancak sadece aşağı yönlü (negatif) riski dikkate alır.",
                "Calmar Oranı": "Yıllıklandırılmış getirinin maksimum düşüşe oranıdır."
            }

            # Metrikleri iki sütun halinde göster
            col1, col2 = st.columns(2)
            metrics_list = list(performance_metrics.items())
            mid_point = (len(metrics_list) + 1) // 2

            with col1:
                for key, value in metrics_list[:mid_point]:
                    st.metric(label=key, value=value, help=metric_tooltips.get(key, ""))
            with col2:
                for key, value in metrics_list[mid_point:]:
                    st.metric(label=key, value=value, help=metric_tooltips.get(key, ""))

            # Performans grafiğini göster
            st.subheader("📈 Strateji Performans Grafiği")
            if equity_curve is not None and drawdown_series is not None:
                performance_fig = plot_performance_summary(equity_curve, drawdown_series)
                st.plotly_chart(performance_fig, use_container_width=True)

        # Tüm işlemlerin tablosunu göster
        st.subheader("📋 Tüm İşlemler")
        st.dataframe(portfolio_results, use_container_width=True)

    else:
        st.info("Backtest sonuçları burada görünecek. Lütfen 'Portföy Backtest Başlat' butonuna basın.")


elif page == "Canlı İzleme":
    # --- ŞİFRE KONTROL MANTIĞI ---

    # Şifrenin secrets.toml dosyasında ayarlanıp ayarlanmadığını kontrol et
    try:
        correct_password = st.secrets["app"]["password"]
    except (KeyError, FileNotFoundError):
        st.error("Uygulama şifresi '.streamlit/secrets.toml' dosyasında ayarlanmamış. Lütfen kurulumu tamamlayın.")
        st.stop()  # Şifre yoksa sayfayı tamamen durdur

    # Kullanıcı giriş yapmamışsa, şifre sorma ekranını göster
    if not st.session_state.get('authenticated', False):
        st.header("🔒 Giriş Gerekli")
        st.info("Canlı İzleme paneline erişmek için lütfen şifreyi girin.")

        password_input = st.text_input("Şifre", type="password", key="password_input")

        if st.button("Giriş Yap"):
            if password_input == correct_password:
                st.session_state.authenticated = True
                st.rerun()  # Sayfayı yeniden yükleyerek içeriği göster
            else:
                st.error("Girilen şifre yanlış.")

    # Kullanıcı başarıyla giriş yapmışsa, sayfanın asıl içeriğini göster
    else:
        # --- YENİ DÜZENLEME: BAŞLIK VE BUTON İÇİN SÜTUNLAR ---
        col1, col2 = st.columns([5, 1])  # Sütunları 5'e 1 oranında ayır

        with col1:
            # Başlığı sol sütuna yerleştir
            st.header("📡 Canlı Strateji Yönetim Paneli")

        with col2:
            # Butonu sağ sütuna yerleştir ve ".sidebar" kısmını kaldır
            if st.button("🔒 Çıkış Yap"):
                st.session_state.authenticated = False
                st.rerun()

        st.info("""
        Bu panelden, kenar çubuğunda (sidebar) yapılandırdığınız ayarlarla birden fazla canlı izleme stratejisi başlatabilirsiniz.
        Arka planda **`multi_worker.py`** script'ini çalıştırdığınızdan emin olun.
        """)

        # --- 1. Yeni Strateji Ekleme Paneli ---
        with st.expander("➕ Yeni Canlı İzleme Stratejisi Ekle", expanded=True):

            new_strategy_name = st.text_input(
                "Strateji Adı",
                placeholder="Örn: BTC/ETH Trend Takip Stratejisi"
            )

            st.write("**Mevcut Kenar Çubuğu Ayarları:**")
            st.write(f"- **Semboller:** `{', '.join(symbols) if symbols else 'Hiçbiri'}`")
            st.write(f"- **Zaman Dilimi:** `{interval}`")
            st.write(f"- **Sinyal Modu:** `{strategy_params['signal_mode']}`")

            if st.button("🚀 Yeni Stratejiyi Canlı İzlemeye Al", type="primary"):
                if not new_strategy_name:
                    st.error("Lütfen stratejiye bir isim verin.")
                elif not symbols:
                    st.error("Lütfen en az bir sembol seçin.")
                else:
                    current_strategy_params = strategy_params.copy()
                    if use_telegram:
                        try:
                            current_strategy_params["telegram_token"] = st.secrets["telegram"]["token"]
                            current_strategy_params["telegram_chat_id"] = st.secrets["telegram"]["chat_id"]
                            current_strategy_params["telegram_enabled"] = True
                        except Exception as e:
                            st.warning(f"Telegram bilgileri okunamadı (.streamlit/secrets.toml kontrol edin): {e}")
                            current_strategy_params["telegram_enabled"] = False
                    else:
                        current_strategy_params["telegram_enabled"] = False

                    new_strategy = {
                        "id": f"strategy_{int(time.time())}",
                        "name": new_strategy_name,
                        "status": "running",
                        "symbols": symbols,
                        "interval": interval,
                        "strategy_params": current_strategy_params
                    }
                    add_or_update_strategy(new_strategy)
                    st.success(f"'{new_strategy_name}' stratejisi başarıyla eklendi!")
                    st.rerun()

        # --- 2. Çalışan Stratejileri Listeleme Paneli ---
        st.subheader("🏃‍♂️ Çalışan Canlı Stratejiler")

        running_strategies = get_all_strategies()

        if not running_strategies:
            st.info("Şu anda çalışan hiçbir canlı strateji yok. Yukarıdaki panelden yeni bir tane ekleyebilirsiniz.")
        else:
            for strategy in running_strategies:
                with st.container(border=True):
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.subheader(f"{strategy.get('name', 'İsimsiz Strateji')}")
                        strategy_symbols = strategy.get('symbols', [])
                        st.caption(
                            f"**ID:** `{strategy.get('id')}` | **Zaman Dilimi:** `{strategy.get('interval')}` | **Semboller:** `{len(strategy_symbols)}`")
                        st.code(f"{', '.join(strategy_symbols)}", language="text")
                    with col2:
                        if st.button("⏹️ Stratejiyi Durdur", key=f"stop_{strategy['id']}", type="secondary"):
                            remove_strategy(strategy['id'])
                            st.warning(f"'{strategy['name']}' stratejisi durduruldu.")
                            st.rerun()  # Butona basıldığında listenin güncellenmesi için burada rerun gerekli ve güvenlidir.

        # --- 3. Son Alarmlar Paneli ---
        st.subheader("🔔 Son Alarmlar (Tüm Stratejilerden)")
        alarm_history = get_alarm_history(limit=20)

        if alarm_history is not None and not alarm_history.empty:
            st.dataframe(alarm_history, use_container_width=True)
        else:
            st.info("Veritabanında henüz kayıtlı bir alarm yok.")


# app.py dosyasında, mevcut 'elif page == "Optimizasyon":' bloğunu silip yerine bunu yapıştırın.

elif page == "Optimizasyon":
    # BAŞLIK DOĞRU YERDE
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


# app.py dosyasındaki if/elif yapısının sonuna bu bloğu ekleyin

elif page == "Detaylı Grafik Analizi":
    st.header("📈 Detaylı Grafik Analizi")

    st.info("""
    Bu sayfada, "Portföy Backtest" sayfasında çalıştırdığınız son backtestin sonuçlarını sembol bazında detaylı olarak inceleyebilirsiniz.
    Grafik üzerindeki göstergeleri (SMA, EMA, Bollinger vb.) kenar çubuğundaki **"📊 Grafik Gösterge Seçenekleri"** menüsünden kontrol edebilirsiniz.
    """)

    # Backtest verisinin var olup olmadığını kontrol et
    if 'backtest_data' not in st.session_state or not st.session_state.backtest_data:
        st.warning("Lütfen önce 'Portföy Backtest' sayfasından bir backtest çalıştırın.")
    else:
        # Backtesti yapılan sembollerden birini seçmek için bir dropdown oluştur
        backtested_symbols = list(st.session_state.backtest_data.keys())
        selected_symbol = st.selectbox("Analiz edilecek sembolü seçin:", backtested_symbols)

        if selected_symbol:
            # Seçilen sembolün DataFrame'ini al
            df = st.session_state.backtest_data[selected_symbol]

            # Kenar çubuğundaki "Göster" checkbox'larının değerlerini bir sözlükte topla
            chart_options = {
                "show_sma": show_sma,
                "show_ema": show_ema,
                "show_bbands": show_bbands,
                "show_vwap": show_vwap,
                "show_adx": show_adx,
                "show_stoch": show_stoch,
                "show_fibonacci": show_fibonacci
            }

            # Fibonacci seviyelerini hesapla (eğer gösterilecekse)
            fib_levels = calculate_fibonacci_levels(df) if show_fibonacci else {}

            # Atıl durumdaki plot_chart fonksiyonunu burada çağırıyoruz!
            fig = plot_chart(df, selected_symbol, fib_levels, chart_options)

            st.plotly_chart(fig, use_container_width=True)
# ------------------------------
# Alarmlar ve Telegram Durumu Paneli

st.sidebar.header("🔔 Son Alarmlar")
# DÜZELTME: Alarmlar artık doğrudan veritabanından, daha güvenilir sorgu ile okunuyor.
alarms = get_alarm_history_db(limit=5)
if alarms is not None and not alarms.empty:
    for _, row in alarms.iterrows():
        fiyat_str = f" @ {row['Fiyat']:.7f}" if pd.notna(row['Fiyat']) else ""

        signal_text = row['Sinyal']
        if "KAPAT" in signal_text or "Kârla" in signal_text or "Zararla" in signal_text:
            emoji = "✅" if "Kârla" in signal_text else "❌" if "Zararla" in signal_text else "🏁"
        elif "LONG" in signal_text:
            emoji = "🟢"
        elif "SHORT" in signal_text:
            emoji = "🔴"
        else:
            emoji = "🔔"

        st.sidebar.write(f"{emoji} **{row['Sembol']}**: {signal_text}{fiyat_str}")
        st.sidebar.caption(f"🕰️ {row['Zaman']}")
else:
    st.sidebar.write("Henüz alarm yok.")

