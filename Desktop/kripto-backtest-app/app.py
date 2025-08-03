import streamlit as st
import pandas as pd
import numpy as np
import json
import time
import itertools
import random
import threading

from utils import get_binance_klines, calculate_fibonacci_levels
from indicators import generate_all_indicators
from features import prepare_features
from ml_model import SignalML
from signals import generate_signals, filter_signals_with_trend, add_higher_timeframe_trend, backtest_signals
from plots import plot_chart
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
    'use_ml': use_ml,
    'use_mta': use_mta,
    'higher_timeframe': higher_timeframe,
    'trend_ema_period': trend_ema_period
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
        cooldown = 0
        for k in range(len(df)):
            if cooldown > 0:
                cooldown -= 1
                continue

            signal = df['Signal'].iloc[k]
            price = df['Close'].iloc[k]
            time_idx = df.index[k]

            if position is None:
                if signal == 'Al' and strategy_params['signal_direction'] != 'Short':
                    position, entry_price, entry_time = 'Long', price, time_idx
                elif signal == 'Sat' and strategy_params['signal_direction'] != 'Long':
                    position, entry_price, entry_time = 'Short', price, time_idx
            else:
                ret = ((price - entry_price) / entry_price * 100) if position == 'Long' else (
                            (entry_price - price) / entry_price * 100)

                exit_condition = False
                sl_triggered = ret <= -strategy_params['stop_loss_pct'] and strategy_params['stop_loss_pct'] > 0
                tp_triggered = ret >= strategy_params['take_profit_pct'] and strategy_params['take_profit_pct'] > 0

                if position == 'Long' and (sl_triggered or tp_triggered or signal == 'Sat'):
                    exit_condition = True
                elif position == 'Short' and (sl_triggered or tp_triggered or signal == 'Al'):
                    exit_condition = True

                if exit_condition:
                    trades.append({
                        'Pozisyon': position, 'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                        'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': price, 'Getiri (%)': round(ret, 2)
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
    st.subheader(f"Detaylı Grafik & Sinyaller — {symbol}")

    df_chart = None
    # Backtest çalıştırıldıysa, hafızadaki işlenmiş veriyi kullan
    if symbol in st.session_state.get('backtest_data', {}):
        df_chart = st.session_state.backtest_data[symbol]
        st.info("Backtest verisi üzerinden grafik çiziliyor.")

    # Eğer backtest verisi yoksa, grafik için veriyi yeniden indir ve işle
    if df_chart is None or df_chart.empty:
        st.info("Grafik için canlı veri indiriliyor...")
        df_chart = get_binance_klines(symbol=symbol, interval=interval, limit=1000)
        if df_chart is not None and not df_chart.empty:
            df_chart = generate_all_indicators(df_chart, **strategy_params)
            df_chart = generate_signals(df_chart, **strategy_params)

            # MTA aktifse, grafik verisine de trendi uygula
            if strategy_params['use_mta']:
                df_higher_chart = get_binance_klines(symbol, strategy_params['higher_timeframe'], limit=1000)
                if df_higher_chart is not None and not df_higher_chart.empty:
                    df_chart = add_higher_timeframe_trend(df_chart, df_higher_chart,
                                                          strategy_params['trend_ema_period'])
                    df_chart = filter_signals_with_trend(df_chart)

    if df_chart is not None and not df_chart.empty:
        fib_levels = calculate_fibonacci_levels(df_chart)
        options = {
            "show_sma": show_sma, "show_ema": show_ema, "show_bbands": show_bbands,
            "show_vwap": show_vwap, "show_adx": show_adx, "show_stoch": show_stoch,
            "show_fibonacci": show_fibonacci,
        }

        # plot_chart fonksiyonu Buy_Signal ve Sell_Signal kolonlarını bekler.
        # Bu kolonları 'Signal' kolonuna göre oluşturalım.
        df_chart['Buy_Signal'] = (df_chart['Signal'] == 'Al')
        df_chart['Sell_Signal'] = (df_chart['Signal'] == 'Sat')

        st.plotly_chart(
            plot_chart(df_chart, symbol, fib_levels, options, ml_signal=strategy_params.get('use_ml', False)),
            use_container_width=True)

        # Ana Trend bilgisini grafiğin altında göster
        if 'Trend' in df_chart.columns:
            last_trend = df_chart['Trend'].iloc[-1]
            trend_color = "green" if last_trend == "Up" else "red"
            st.markdown(
                f"### Ana Trend ({strategy_params['higher_timeframe']}): <font color='{trend_color}'>{last_trend}</font>",
                unsafe_allow_html=True)
    else:
        st.warning(f"{symbol} için grafik verisi bulunamadı veya işlenemedi.")

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