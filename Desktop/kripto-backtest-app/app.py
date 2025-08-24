import streamlit as st
import pandas as pd
import numpy as np
import json
import time
import itertools
import random
import threading
import os
from datetime import datetime
from stable_baselines3 import PPO
from market_regime import get_market_regime
from orchestrator import run_orchestrator_cycle, get_strategy_dna
from evolution_chamber import run_evolution_cycle
from utils import get_binance_klines, calculate_fibonacci_levels, analyze_backtest_results
from indicators import generate_all_indicators
from features import prepare_features
from ml_model import SignalML
from signals import generate_signals, filter_signals_with_trend, add_higher_timeframe_trend, backtest_signals
from plots import plot_chart, plot_performance_summary
from telegram_alert import send_telegram_message
from alarm_log import log_alarm, get_alarm_history
import plotly.express as px
from database import (
    add_or_update_strategy, remove_strategy, get_all_strategies,
    initialize_db, get_alarm_history_db, get_all_open_positions,
    get_live_closed_trades_metrics, update_strategy_status,
    issue_manual_action,
    get_all_rl_models_info,
    get_rl_model_by_id
)
from utils import (
    get_current_prices, get_fear_and_greed_index, get_btc_dominance
)
from trading_env import TradingEnv
from rl_trainer import train_rl_agent


def apply_full_strategy_params(strategy, is_editing=False):
    """
    Seçilen bir stratejinin tüm parametrelerini session_state'e uygular.
    Eğer is_editing True ise, düzenleme modunu aktif hale getirir.
    """
    params = strategy.get('strategy_params', {})
    strategy_name = strategy.get('name', 'İsimsiz Strateji')

    # Eğer düzenleme modundaysak, ID ve ismi session_state'e kaydet
    if is_editing:
        st.session_state.editing_strategy_id = strategy.get('id')
        st.session_state.editing_strategy_name = strategy_name

    # Kenar çubuğu widget'larının anahtarlarını strateji verileriyle doldur
    st.session_state.symbols_key = strategy.get('symbols', ["BTCUSDT"])
    st.session_state.interval_key = strategy.get('interval', '1h')
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
    direction_map = {"Long": "Long Only", "Short": "Short Only", "Both": "Long & Short"}
    st.session_state.signal_mode_key = direction_map.get(params.get('signal_direction', 'Both'), "Long & Short")
    st.session_state.signal_logic_key = "AND (Teyitli)" if params.get('signal_mode') == 'and' else "OR (Hızlı)"
    st.session_state.cooldown_bars_key = params.get('cooldown_bars', 3)
    st.session_state.commission_pct_key = params.get('commission_pct', 0.1)
    if params.get('atr_multiplier', 0) > 0:
        st.session_state.sl_type_key = "ATR"
        st.session_state.atr_multiplier_key = params.get('atr_multiplier', 2.0)
    else:
        st.session_state.sl_type_key = "Yüzde (%)"
        st.session_state.stop_loss_pct_key = params.get('stop_loss_pct', 2.0)
    st.session_state.move_sl_to_be = params.get('move_sl_to_be', True)
    st.session_state.tp1_pct_key = params.get('tp1_pct', 5.0)
    st.session_state.tp1_size_key = params.get('tp1_size_pct', 50)
    st.session_state.tp2_pct_key = params.get('tp2_pct', 10.0)
    st.session_state.tp2_size_key = params.get('tp2_size_pct', 50)
    st.session_state.use_mta_key = params.get('use_mta', True)
    st.session_state.higher_timeframe_key = params.get('higher_timeframe', '4h')
    st.session_state.trend_ema_period_key = params.get('trend_ema_period', 50)
    st.session_state.puzzle_bot = params.get('use_puzzle_bot', False)
    st.session_state.ml_toggle = params.get('use_ml', False)
    st.session_state.telegram_alerts = params.get('telegram_enabled', True)

    if is_editing:
        st.toast(f"'{strategy_name}' için düzenleme modu aktif!", icon="✍️")
    else:
        st.toast(f"'{strategy_name}' stratejisinin tüm parametreleri yüklendi!", icon="✅")




def run_rl_backtest(model_id, backtest_df_raw):
    """Eğitilmiş bir RL modelini ID'sine göre veritabanından yükler ve backtest yapar."""
    model_buffer = get_rl_model_by_id(model_id)
    if not model_buffer:
        st.error(f"Veritabanında Model ID'si {model_id} olan bir model bulunamadı.")
        return pd.DataFrame(), pd.DataFrame()

    model = PPO.load(model_buffer)
    env = TradingEnv(backtest_df_raw.copy())
    obs, _ = env.reset()

    df_with_actions = env.df.copy()
    df_with_actions['RL_Signal'] = 'Bekle'
    model_info = next((m for m in st.session_state.rl_models_list if m['id'] == model_id), None)
    df_with_actions.attrs['symbol'] = model_info['name'].split('_')[1] if model_info else "UNKNOWN"

    trades = []
    # ... (Geri kalan backtest mantığı önceki adımdaki gibi aynı)
    while True:
        action, _states = model.predict(obs, deterministic=True)
        obs, reward, done, truncated, info = env.step(action)
        current_step_index = env.df.index[env.current_step]
        if action == 1: df_with_actions.loc[current_step_index, 'RL_Signal'] = 'Al'
        elif action == 2: df_with_actions.loc[current_step_index, 'RL_Signal'] = 'Sat'
        is_opening = env.position == 1 and (not trades or 'Çıkış Zamanı' in trades[-1])
        is_closing = env.position == 0 and trades and 'Çıkış Zamanı' not in trades[-1]
        if is_opening: trades.append({'Pozisyon': 'Long', 'Giriş Zamanı': current_step_index, 'Giriş Fiyatı': env.entry_price})
        elif is_closing:
            trade = trades[-1]
            trade['Çıkış Zamanı'] = current_step_index
            trade['Çıkış Fiyatı'] = env.df['Close'].loc[current_step_index]
            pnl = ((trade['Çıkış Fiyatı'] - trade['Giriş Fiyatı']) / trade['Giriş Fiyatı']) * 100
            trade['Getiri (%)'] = round(pnl, 2)
        if done: break
    if trades and 'Çıkış Zamanı' not in trades[-1]: trades.pop(-1)
    return pd.DataFrame(trades), df_with_actions


initialize_db()

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

if 'editing_strategy_id' not in st.session_state:
    st.session_state.editing_strategy_id = None

if 'editing_strategy_name' not in st.session_state:
    st.session_state.editing_strategy_name = None

CONFIG_FILE = "config.json"


def load_config():
    """config.json dosyasından ayarları yükler."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
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


st.set_page_config(page_title="Veritas Point Labs", layout="wide", page_icon="logo.png",)
st.title("⚛️ Veritas Point Labs")


if 'config' not in st.session_state:
    st.session_state.config = load_config()
config = st.session_state.config

st.sidebar.header("🔎 Sayfa Seçimi")
page = st.sidebar.radio(
    "Sayfa",
    ["📊 Simülasyon", "🧪 Deney Odası", "🔬 Laboratuvar"]
)

if "live_tracking" not in st.session_state:
    st.session_state.live_tracking = False

# ==============================================================================
# --- BAŞLANGIÇ: TÜM WIDGET'LAR İÇİN SESSION STATE TANIMLAMALARI ---
# ==============================================================================
# Her widget için bir başlangıç değeri olduğundan emin oluyoruz.
# Bu, kodun daha temiz ve hatasız çalışmasını sağlar.
DEFAULTS = {
    'use_mta_key': True, 'higher_timeframe_key': '4h', 'trend_ema_period_key': 50,
    'puzzle_bot': False, 'telegram_alerts': True, 'ml_toggle': False,
    'ml_forward_window': 5, 'ml_threshold': 0.5, 'use_rsi': True, 'use_macd': True,
    'use_bb': False, 'use_adx': False, 'rsi_period': 14, 'rsi_buy_key': 30,
    'rsi_sell_key': 70, 'macd_fast': 12, 'macd_slow': 26, 'macd_signal': 9,
    'adx_threshold_key': 25, 'symbols_key': ["BTCUSDT", "ETHUSDT"], 'interval_key': '1h',
    'signal_mode_key': "Long & Short", 'signal_logic_key': "OR (Hızlı)",
    'cooldown_bars_key': 3, 'commission_pct_key': 0.1, 'sl_type_key': "ATR",
    'stop_loss_pct_key': 2.0, 'atr_multiplier_key': 2.0, 'move_sl_to_be': True,
    'tp1_pct_key': 5.0, 'tp1_size_key': 50, 'tp2_pct_key': 10.0, 'tp2_size_key': 50
}
for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value


# ==============================================================================
# --- BİTİŞ: SESSION STATE TANIMLAMALARI ---
# ==============================================================================


def rerun_if_changed(widget_value, session_state_key):
    """Widget değeri değiştiyse session_state'i günceller ve rerun yapar."""
    if widget_value != st.session_state[session_state_key]:
        st.session_state[session_state_key] = widget_value
        st.rerun()


# --- KENAR ÇUBUĞU WIDGET'LARI ---

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
    use_mta_selection = st.checkbox("Ana Trend Filtresini Kullan", value=st.session_state.use_mta_key, help="...")
    rerun_if_changed(use_mta_selection, 'use_mta_key')
    use_mta = st.session_state.use_mta_key

    if use_mta:
        timeframe_map = {"15m": "1h", "1h": "4h", "4h": "1d"}
        current_interval = st.session_state.get('interval_key', '1h')
        default_higher_tf = timeframe_map.get(current_interval, "4h")
        higher_tf_options = ["1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d", "1w"]
        try:
            default_index = higher_tf_options.index(st.session_state.higher_timeframe_key)
        except ValueError:
            default_index = 2

        higher_timeframe_selection = st.selectbox("Ana Trend için Üst Zaman Dilimi", options=higher_tf_options,
                                                  index=default_index)
        rerun_if_changed(higher_timeframe_selection, 'higher_timeframe_key')
        higher_timeframe = st.session_state.higher_timeframe_key

        trend_ema_period_selection = st.slider("Trend EMA Periyodu", 20, 200, st.session_state.trend_ema_period_key,
                                               help="...")
        rerun_if_changed(trend_ema_period_selection, 'trend_ema_period_key')
        trend_ema_period = st.session_state.trend_ema_period_key
    else:
        higher_timeframe = None
        trend_ema_period = 50

with st.sidebar.expander("🔧 Diğer Parametreler", expanded=False):
    st.subheader("🧩 Puzzle Strateji Botu")
    use_puzzle_bot_selection = st.checkbox("Puzzle Strateji Botunu Kullan", value=st.session_state.puzzle_bot)
    rerun_if_changed(use_puzzle_bot_selection, 'puzzle_bot')
    use_puzzle_bot = st.session_state.puzzle_bot

    st.subheader("📡 Telegram Bildirimleri")
    use_telegram_selection = st.checkbox("Telegram Bildirimlerini Aç", value=st.session_state.telegram_alerts)
    rerun_if_changed(use_telegram_selection, 'telegram_alerts')
    use_telegram = st.session_state.telegram_alerts

    st.subheader("🤖 ML Tahmin Parametreleri")
    use_ml_selection = st.checkbox("Makine Öğrenmesi Tahmini Kullan", value=st.session_state.ml_toggle)
    rerun_if_changed(use_ml_selection, 'ml_toggle')
    use_ml = st.session_state.ml_toggle

    if use_ml:
        forward_window_selection = st.slider("📈 Gelecek Bar (target)", 1, 20, st.session_state.ml_forward_window)
        rerun_if_changed(forward_window_selection, 'ml_forward_window')
        forward_window = st.session_state.ml_forward_window

        target_thresh_selection = st.slider("🎯 Target Eşik (%)", 0.1, 5.0, st.session_state.ml_threshold, step=0.1)
        rerun_if_changed(target_thresh_selection, 'ml_threshold')
        target_thresh = st.session_state.ml_threshold
    else:
        forward_window, target_thresh = None, None

st.sidebar.header("🔔 Sinyal Kriterleri Seçenekleri")
col1, col2 = st.sidebar.columns(2)
use_rsi_selection = col1.checkbox("RSI Sinyali", value=st.session_state.use_rsi)
rerun_if_changed(use_rsi_selection, 'use_rsi')
use_rsi = st.session_state.use_rsi

use_macd_selection = col2.checkbox("MACD Sinyali", value=st.session_state.use_macd)
rerun_if_changed(use_macd_selection, 'use_macd')
use_macd = st.session_state.use_macd

col3, col4 = st.sidebar.columns(2)
use_bb_selection = col3.checkbox("Bollinger Sinyali", value=st.session_state.use_bb)
rerun_if_changed(use_bb_selection, 'use_bb')
use_bb = st.session_state.use_bb

use_adx_selection = col4.checkbox("ADX Sinyali", value=st.session_state.use_adx)
rerun_if_changed(use_adx_selection, 'use_adx')
use_adx = st.session_state.use_adx

if use_rsi:
    rsi_period_selection = st.sidebar.number_input("RSI Periyodu", 2, 100, st.session_state.rsi_period)
    rerun_if_changed(rsi_period_selection, 'rsi_period')
    rsi_period = st.session_state.rsi_period

    rsi_buy_selection = st.sidebar.slider("RSI Alış Eşiği", 0, 50, st.session_state.rsi_buy_key, 1)
    rerun_if_changed(rsi_buy_selection, 'rsi_buy_key')
    rsi_buy = st.session_state.rsi_buy_key

    rsi_sell_selection = st.sidebar.slider("RSI Satış Eşiği", 50, 100, st.session_state.rsi_sell_key, 1)
    rerun_if_changed(rsi_sell_selection, 'rsi_sell_key')
    rsi_sell = st.session_state.rsi_sell_key
else:
    rsi_buy, rsi_sell, rsi_period = 30, 70, 14

if use_macd:
    macd_fast_selection = st.sidebar.slider("MACD Fast Periyodu", 5, 20, st.session_state.macd_fast)
    rerun_if_changed(macd_fast_selection, 'macd_fast')
    macd_fast = st.session_state.macd_fast

    macd_slow_selection = st.sidebar.slider("MACD Slow Periyodu", 10, 40, st.session_state.macd_slow)
    rerun_if_changed(macd_slow_selection, 'macd_slow')
    macd_slow = st.session_state.macd_slow

    macd_signal_selection = st.sidebar.slider("MACD Signal Periyodu", 5, 15, st.session_state.macd_signal)
    rerun_if_changed(macd_signal_selection, 'macd_signal')
    macd_signal = st.session_state.macd_signal
else:
    macd_fast, macd_slow, macd_signal = 12, 26, 9

adx_threshold_selection = st.sidebar.slider("ADX Eşiği", 10, 50, st.session_state.adx_threshold_key)
rerun_if_changed(adx_threshold_selection, 'adx_threshold_key')
adx_threshold = st.session_state.adx_threshold_key

# --- Sembol ve Zaman Dilimi Seçimi ---
symbols_selection = st.multiselect(
    "📈 Portföyde test edilecek semboller",
    [
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "ADAUSDT", "DOGEUSDT",
        "MATICUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT", "SHIBUSDT", "AVAXUSDT", "UNIUSDT",
        "LINKUSDT", "ALGOUSDT", "ATOMUSDT", "BCHUSDT", "XLMUSDT", "VETUSDT", "FILUSDT",
        "ICPUSDT", "THETAUSDT", "EOSUSDT", "AAVEUSDT", "MKRUSDT", "KSMUSDT", "XTZUSDT",
        "NEARUSDT", "CAKEUSDT", "FTMUSDT", "GRTUSDT", "SNXUSDT", "RUNEUSDT", "CHZUSDT",
        "ZILUSDT", "DASHUSDT", "SANDUSDT", "KAVAUSDT", "COMPUSDT", "LUNAUSDT", "ENJUSDT",
        "BATUSDT", "NANOUSDT", "1INCHUSDT", "ZRXUSDT", "CELRUSDT", "HNTUSDT", "FTTUSDT", "GALAUSDT"
    ],
    default=st.session_state.symbols_key
)
rerun_if_changed(symbols_selection, 'symbols_key')
symbols = st.session_state.symbols_key

timeframe_options = ["15m", "1h", "4h"]
timeframe_index = timeframe_options.index(st.session_state.interval_key)
interval_selection = st.selectbox("⏳ Zaman Dilimi Seçin", options=timeframe_options, index=timeframe_index)
rerun_if_changed(interval_selection, 'interval_key')
interval = st.session_state.interval_key

results_section = st.container()
optimize_section = st.container()

with st.expander("⚙️ Strateji Gelişmiş Ayarlar", expanded=False):
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("**Sinyal & İşlem Ayarları**")
        signal_mode_options = ["Long Only", "Short Only", "Long & Short"]
        signal_mode_index = signal_mode_options.index(st.session_state.signal_mode_key)
        signal_mode = st.selectbox("Sinyal Modu", signal_mode_options, index=signal_mode_index)
        rerun_if_changed(signal_mode, 'signal_mode_key')

        signal_logic_options = ["AND (Teyitli)", "OR (Hızlı)"]
        signal_logic_index = signal_logic_options.index(st.session_state.signal_logic_key)
        signal_logic = st.selectbox("Sinyal Mantığı", signal_logic_options, index=signal_logic_index, help="...")
        rerun_if_changed(signal_logic, 'signal_logic_key')

        cooldown_bars = st.slider("İşlem Arası Bekleme (bar)", 0, 10, st.session_state.cooldown_bars_key)
        rerun_if_changed(cooldown_bars, 'cooldown_bars_key')

        commission_pct = st.slider("İşlem Başına Komisyon (%)", 0.0, 0.5, st.session_state.commission_pct_key,
                                   step=0.01, help="...")
        rerun_if_changed(commission_pct, 'commission_pct_key')

    with col2:
        st.markdown("**Zarar Durdur (Stop-Loss)**")
        sl_type_options = ["Yüzde (%)", "ATR"]
        sl_type_index = sl_type_options.index(st.session_state.sl_type_key)
        sl_type = st.radio("Stop-Loss Türü", sl_type_options, index=sl_type_index, horizontal=True)
        rerun_if_changed(sl_type, 'sl_type_key')

        if sl_type == "Yüzde (%)":
            stop_loss_pct = st.slider("Stop Loss (%)", 0.0, 10.0, st.session_state.stop_loss_pct_key, step=0.1)
            rerun_if_changed(stop_loss_pct, 'stop_loss_pct_key')
            atr_multiplier = 0
        else:
            atr_multiplier = st.slider("ATR Çarpanı", 1.0, 5.0, st.session_state.atr_multiplier_key, step=0.1,
                                       help="...")
            rerun_if_changed(atr_multiplier, 'atr_multiplier_key')
            stop_loss_pct = 0

    with col3:
        st.markdown("**Kademeli Kâr Al (Take-Profit)**")
        move_sl_to_be = st.checkbox("TP1 sonrası Stop'u Girişe Çek", value=st.session_state.move_sl_to_be, help="...")
        rerun_if_changed(move_sl_to_be, 'move_sl_to_be')

        tp1_pct = st.slider("TP1 Kâr (%)", 0.0, 20.0, st.session_state.tp1_pct_key, step=0.1)
        rerun_if_changed(tp1_pct, 'tp1_pct_key')

        tp1_size_pct = st.slider("TP1 Pozisyon Kapatma (%)", 0, 100, st.session_state.tp1_size_key, help="...")
        rerun_if_changed(tp1_size_pct, 'tp1_size_key')

        tp2_pct = st.slider("TP2 Kâr (%)", 0.0, 50.0, st.session_state.tp2_pct_key, step=0.1)
        rerun_if_changed(tp2_pct, 'tp2_pct_key')

        tp2_size_pct = st.slider("TP2 Pozisyon Kapatma (%)", 0, 100, st.session_state.tp2_size_key, help="...")
        rerun_if_changed(tp2_size_pct, 'tp2_size_key')

strategy_params = {
    'sma': sma_period, 'ema': ema_period, 'bb_period': bb_period, 'bb_std': bb_std,
    'rsi_buy': rsi_buy, 'rsi_sell': rsi_sell, 'rsi_period': rsi_period,
    'macd_fast': macd_fast, 'macd_slow': macd_slow, 'macd_signal': macd_signal,
    'adx_period': 14, 'adx_threshold': adx_threshold,
    'use_rsi': use_rsi, 'use_macd': use_macd, 'use_bb': use_bb, 'use_adx': use_adx,
    'stop_loss_pct': stop_loss_pct,
    'atr_multiplier': atr_multiplier,
    'cooldown_bars': cooldown_bars,
    'signal_mode': 'and' if signal_logic == "AND (Teyitli)" else 'or',
    'signal_direction': {"Long Only": "Long", "Short Only": "Short", "Long & Short": "Both"}[signal_mode],
    'use_puzzle_bot': use_puzzle_bot, 'use_ml': use_ml, 'use_mta': use_mta,
    'higher_timeframe': higher_timeframe, 'trend_ema_period': trend_ema_period,
    'commission_pct': 0.1,
    'tp1_pct': tp1_pct, 'tp1_size_pct': tp1_size_pct,
    'tp2_pct': tp2_pct, 'tp2_size_pct': tp2_size_pct,
    'move_sl_to_be': move_sl_to_be

}

if "live_running" not in st.session_state: st.session_state.live_running = False
if "live_thread_started" not in st.session_state: st.session_state.live_thread_started = False
if "last_signal" not in st.session_state: st.session_state.last_signal = "Henüz sinyal yok."
if "backtest_results" not in st.session_state: st.session_state.backtest_results = pd.DataFrame()


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



@st.cache_data(ttl=60) # Sinyali 1 dakika boyunca önbellekte tut
def get_latest_signal(symbol, interval, strategy_params):
    """Belirli bir sembol ve strateji için en güncel sinyali hesaplar."""
    df = get_binance_klines(symbol=symbol, interval=interval, limit=200)
    if df is None or df.empty:
        return "Veri Yok"

    df = generate_all_indicators(df, **strategy_params)

    # --- BAŞLANGIÇ: DÜZELTME (Sıralama Değiştirildi) ---
    # ÖNCE sinyalleri üret
    df = generate_signals(df, **strategy_params)

    # SONRA üretilmiş sinyalleri trende göre filtrele
    if strategy_params.get('use_mta', False):
        df_higher = get_binance_klines(symbol=symbol, interval=strategy_params['higher_timeframe'], limit=1000)
        if df_higher is not None and not df_higher.empty:
            df = add_higher_timeframe_trend(df, df_higher, strategy_params['trend_ema_period'])
            df = filter_signals_with_trend(df)
    # --- BİTİŞ: DÜZELTME ---
    return df['Signal'].iloc[-1]




def run_portfolio_backtest(symbols, interval, strategy_params):
    """
    Kademeli Kâr Alma ve Stop'u Başa Çekme özelliklerini içeren,
    gerçekçi backtest fonksiyonu.
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

        df_higher = None
        current_use_mta = strategy_params.get('use_mta', False)
        if current_use_mta:
            df_higher = get_binance_klines(symbol=symbol, interval=strategy_params['higher_timeframe'], limit=1000)
            if df_higher is None or df_higher.empty: current_use_mta = False

        df = generate_all_indicators(df, **strategy_params)
        df = generate_signals(df, **strategy_params)

        if current_use_mta and df_higher is not None:
            df = add_higher_timeframe_trend(df, df_higher, strategy_params['trend_ema_period'])
            df = filter_signals_with_trend(df)

        trades = []
        position, entry_price, entry_time, stop_loss_price, cooldown = None, 0, None, 0, 0
        position_size = 0
        tp1_target, tp2_target = 0, 0
        tp1_hit, tp2_hit = False, False

        for k in range(1, len(df)):
            if cooldown > 0:
                cooldown -= 1
                continue

            prev_row, current_row = df.iloc[k - 1], df.iloc[k]
            signal, open_price, low_price, high_price = prev_row['Signal'], current_row['Open'], current_row['Low'], \
                current_row['High']
            time_idx, current_atr = current_row.name, prev_row.get('ATR', 0)

            if position is not None:
                exit_price, exit_reason = None, ""

                if (position == 'Long' and low_price <= stop_loss_price) or \
                        (position == 'Short' and high_price >= stop_loss_price):
                    exit_price, exit_reason = stop_loss_price, "Stop-Loss"

                else:
                    if position == 'Long':
                        if not tp1_hit and high_price >= tp1_target:
                            size_to_close = position_size * (strategy_params['tp1_size_pct'] / 100.0)
                            position_size -= size_to_close
                            ret = ((tp1_target - entry_price) / entry_price * 100) - strategy_params['commission_pct']
                            trades.append({'Pozisyon': f"Long TP1 ({strategy_params['tp1_size_pct']}%)",
                                           'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                                           'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': tp1_target,
                                           'Getiri (%)': round(ret, 2)})
                            tp1_hit = True
                            if strategy_params['move_sl_to_be']:
                                stop_loss_price = entry_price

                        if not tp2_hit and high_price >= tp2_target:
                            size_to_close = position_size * (strategy_params['tp2_size_pct'] / 100.0)
                            position_size -= size_to_close
                            ret = ((tp2_target - entry_price) / entry_price * 100) - strategy_params['commission_pct']
                            trades.append({'Pozisyon': f"Long TP2 ({strategy_params['tp2_size_pct']}%)",
                                           'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                                           'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': tp2_target,
                                           'Getiri (%)': round(ret, 2)})
                            tp2_hit = True

                    elif position == 'Short':
                        if not tp1_hit and low_price <= tp1_target:
                            size_to_close = position_size * (strategy_params['tp1_size_pct'] / 100.0)
                            position_size -= size_to_close
                            ret = ((entry_price - tp1_target) / entry_price * 100) - strategy_params['commission_pct']
                            trades.append({'Pozisyon': f"Short TP1 ({strategy_params['tp1_size_pct']}%)",
                                           'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                                           'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': tp1_target,
                                           'Getiri (%)': round(ret, 2)})
                            tp1_hit = True
                            if strategy_params['move_sl_to_be']:
                                stop_loss_price = entry_price

                        if not tp2_hit and low_price <= tp2_target:
                            size_to_close = position_size * (strategy_params['tp2_size_pct'] / 100.0)
                            position_size -= size_to_close
                            ret = ((entry_price - tp2_target) / entry_price * 100) - strategy_params['commission_pct']
                            trades.append({'Pozisyon': f"Short TP2 ({strategy_params['tp2_size_pct']}%)",
                                           'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                                           'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': tp2_target,
                                           'Getiri (%)': round(ret, 2)})
                            tp2_hit = True

                if (position == 'Long' and signal == 'Short') or \
                        (position == 'Short' and signal == 'Al'):
                    exit_price, exit_reason = open_price, "Karşıt Sinyal"

                if exit_price is not None or position_size <= 0.01:
                    if position_size > 0:
                        ret = ((exit_price - entry_price) / entry_price * 100) if position == 'Long' else (
                                (entry_price - exit_price) / entry_price * 100)
                        ret -= strategy_params['commission_pct']
                        trades.append({'Pozisyon': f"{position} Kalan ({exit_reason})", 'Giriş Zamanı': entry_time,
                                       'Çıkış Zamanı': time_idx, 'Giriş Fiyatı': entry_price,
                                       'Çıkış Fiyatı': exit_price, 'Getiri (%)': round(ret, 2)})

                    position, cooldown, position_size = None, strategy_params.get('cooldown_bars', 3), 0

            if position is None:
                entry_signal = None
                if signal == 'Al' and strategy_params['signal_direction'] != 'Short':
                    entry_signal = 'Long'
                elif signal == 'Short' and strategy_params['signal_direction'] != 'Long':
                    entry_signal = 'Short'

                if entry_signal:
                    position, entry_price, entry_time = entry_signal, open_price, time_idx
                    position_size, tp1_hit, tp2_hit = 1.0, False, False

                    if entry_signal == 'Long':
                        stop_loss_price = entry_price * (1 - strategy_params['stop_loss_pct'] / 100) if strategy_params[
                                                                                                            'atr_multiplier'] <= 0 else entry_price - (
                                current_atr * strategy_params['atr_multiplier'])
                        tp1_target = entry_price * (1 + strategy_params['tp1_pct'] / 100.0)
                        tp2_target = entry_price * (1 + strategy_params['tp2_pct'] / 100.0)
                    else:
                        stop_loss_price = entry_price * (1 + strategy_params['stop_loss_pct'] / 100) if strategy_params[
                                                                                                            'atr_multiplier'] <= 0 else entry_price + (
                                current_atr * strategy_params['atr_multiplier'])
                        tp1_target = entry_price * (1 - strategy_params['tp1_pct'] / 100.0)
                        tp2_target = entry_price * (1 - strategy_params['tp2_pct'] / 100.0)

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


def run_portfolio_optimization(symbols, interval, strategy_params):
    st.info("""
    Bu bölümde, stratejinizin en iyi performans gösteren parametrelerini bulmak için binlerce kombinasyonu test edebilirsiniz.
    Lütfen optimize etmek istediğiniz hedefi ve parametrelerin test edileceği aralıkları seçin.
    """)

    st.subheader("1. Optimizasyon Hedefini Seçin")
    optimization_target = st.selectbox(
        "Hangi Metriğe Göre Optimize Edilsin?",
        options=["Sharpe Oranı (Yıllık)", "Sortino Oranı (Yıllık)", "Calmar Oranı", "Maksimum Düşüş (Drawdown) (%)",
                 "Toplam Getiri (%)"],
        index=0,
        help="Optimizasyon, seçtiğiniz bu metriği maksimize (veya Drawdown için minimize) etmeye çalışacaktır."
    )

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

    st.subheader("3. Optimizasyonu Başlatın")

    if st.button("🚀 Optimizasyonu Başlat", type="primary"):
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

        max_tests = 200
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
            current_params['stop_loss_pct'] = 0

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
                            gross_ret = ((exit_price - entry_price) / entry_price * 100) if position == 'Long' else (
                                    (entry_price - exit_price) / entry_price * 100)

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


if page == "🔬 Laboratuvar":
    try:
        correct_password = st.secrets["app"]["password"]
    except (KeyError, FileNotFoundError):
        st.error("Uygulama şifresi '.streamlit/secrets.toml' dosyasında ayarlanmamış. Lütfen kurulumu tamamlayın.")
        st.stop()

    if not st.session_state.get('authenticated', False):
        st.info("Yönetim paneline erişmek için lütfen şifreyi girin.")
        password_input = st.text_input("Şifre", type="password", key="password_input")
        if st.button("Giriş Yap"):
            if password_input == correct_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Girilen şifre yanlış.")
    else:
        main_col1, main_col2 = st.columns([5, 1])
        with main_col1:
            st.header("📡 Canlı Strateji Yönetim Paneli")
        with main_col2:
            if st.button("🔒 Çıkış Yap"):
                st.session_state.authenticated = False
                st.rerun()

        tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(
            ["📈 Genel Bakış", "⚙️ Strateji Yönetimi", "🤖 Strateji Koçu", "📊 Açık Pozisyonlar", "🔔 Alarm Geçmişi", "🧬 Gen Havuzu", "🤖 RL Ajan" ])

        # Sekme 1: Genel Bakış
        with tab1:
            st.subheader("🌐 Global Piyasa Durumu")
            fng_data = get_fear_and_greed_index()
            btc_dom = get_btc_dominance()
            col1_market, col2_market = st.columns(2)
            with col1_market:
                if fng_data:
                    st.metric(
                        label=f"Korku ve Hırs Endeksi: {fng_data['classification']}",
                        value=fng_data['value']
                    )
                else:
                    st.metric(label="Korku ve Hırs Endeksi", value="Veri Alınamadı")
            with col2_market:
                if btc_dom:
                    st.metric(label="Bitcoin Dominansı", value=f"{btc_dom}%")
                else:
                    st.metric(label="Bitcoin Dominansı", value="Veri Alınamadı")

            st.markdown("---")

            st.subheader("🚀 Genel Portföy Durumu")
            open_positions_df_for_pnl = get_all_open_positions()
            live_metrics_overall = get_live_closed_trades_metrics()
            current_prices = {}
            if not open_positions_df_for_pnl.empty:
                symbols_with_open_positions = open_positions_df_for_pnl['Sembol'].unique().tolist()
                current_prices = get_current_prices(symbols_with_open_positions)

            total_pnl = 0.0
            pnl_by_strategy = {}
            if not open_positions_df_for_pnl.empty and current_prices:
                for _, row in open_positions_df_for_pnl.iterrows():
                    symbol = row['Sembol']
                    strategy_name = row['Strateji Adı']
                    position_type = row['Pozisyon']
                    entry_price = row['Giriş Fiyatı']
                    if symbol in current_prices:
                        current_price = current_prices[symbol]
                        pnl_percent = 0
                        if position_type == 'Long':
                            pnl_percent = ((current_price - entry_price) / entry_price) * 100
                        elif position_type == 'Short':
                            pnl_percent = ((entry_price - current_price) / entry_price) * 100
                        total_pnl += pnl_percent
                        pnl_by_strategy.setdefault(strategy_name, 0.0)
                        pnl_by_strategy[strategy_name] += pnl_percent

            col1_pnl, col2_pnl, col3_pnl = st.columns(3)
            col1_pnl.metric(label="Açık Pozisyonlar Toplam Kâr/Zarar", value=f"{total_pnl:.2f}%")
            col2_pnl.metric(label="Genel Başarı Oranı (Kapalı)", value=f"{live_metrics_overall['Başarı Oranı (%)']}%",
                            help=f"Canlıda kapanan {live_metrics_overall['Toplam İşlem']} işlem üzerinden hesaplanmıştır.")
            most_profitable_strategy = max(pnl_by_strategy, key=pnl_by_strategy.get) if pnl_by_strategy else "--"
            col3_pnl.metric(label="En Kârlı Strateji (Anlık)", value=most_profitable_strategy)

            if pnl_by_strategy:
                pnl_df = pd.DataFrame(list(pnl_by_strategy.items()), columns=['Strateji', 'PnL (%)'])
                fig = px.pie(pnl_df, values='PnL (%)', names='Strateji', title='Strateji Bazında Anlık Kâr Dağılımı',
                             color_discrete_sequence=px.colors.sequential.RdBu)
                st.plotly_chart(fig, use_container_width=True)

        with tab2:  # Strateji Yönetimi
            # --- YENİ: Eğitilmiş RL Modellerini Veritabanından Çek ---
            st.session_state.rl_models_list = get_all_rl_models_info()
            # Model seçenekleri için bir sözlük oluştur (None anahtarı "Hiçbiri" anlamına gelir)
            model_options = {model['id']: model['name'] for model in st.session_state.rl_models_list}
            model_options[None] = "Hiçbiri (Standart Sinyal)"

            # Eğer düzenleme modu aktifse, "Değişiklikleri Kaydet" panelini göster
            if st.session_state.get('editing_strategy_id'):
                with st.expander(f"✍️ '{st.session_state.editing_strategy_name}' Stratejisini Güncelle", expanded=True):
                    st.info(
                        "Kenar çubuğunda yaptığınız değişiklikleri kaydedin veya bu strateji için bir RL Ajanı atayın.")

                    # --- GÜNCELLENDİ: RL Modeli Atama ---
                    # Mevcut stratejinin verisini çekerek seçili olan modeli bul
                    strategy_data = next(
                        (s for s in get_all_strategies() if s['id'] == st.session_state.editing_strategy_id), {})
                    current_model_id = strategy_data.get('rl_model_id')

                    # Selectbox'ı oluştur
                    selected_model_id = st.selectbox(
                        "Sinyal Üretici Olarak Kullanılacak RL Ajanı",
                        options=list(model_options.keys()),  # Opsiyonlar ID'ler olacak
                        format_func=lambda x: model_options[x],  # Gösterilecek metin isimler olacak
                        index=list(model_options.keys()).index(
                            current_model_id) if current_model_id in model_options.keys() else list(
                            model_options.keys()).index(None),  # Mevcut ID'yi seç
                        key=f"rl_model_edit_{st.session_state.editing_strategy_id}",
                        help="Bir RL ajanı seçerseniz, bu strateji artık kenar çubuğundaki RSI, MACD gibi ayarlara göre değil, doğrudan yapay zekanın kararlarına göre sinyal üretecektir."
                    )

                    save_col, cancel_col = st.columns(2)
                    with save_col:
                        if st.button("💾 Değişiklikleri Kaydet", type="primary", use_container_width=True):
                            strategy_to_update = {
                                "id": st.session_state.editing_strategy_id,
                                "name": st.session_state.editing_strategy_name,
                                "status": "running",
                                "symbols": symbols,
                                "interval": interval,
                                "strategy_params": strategy_params,
                                "rl_model_id": selected_model_id
                            }
                            add_or_update_strategy(strategy_to_update)
                            st.toast(f"'{st.session_state.editing_strategy_name}' başarıyla güncellendi!", icon="💾")
                            st.session_state.editing_strategy_id = None
                            st.session_state.editing_strategy_name = None
                            st.rerun()

                    with cancel_col:
                        if st.button("❌ İptal Et", use_container_width=True):
                            st.toast("Değişiklikler iptal edildi.", icon="↩️")
                            st.session_state.editing_strategy_id = None
                            st.session_state.editing_strategy_name = None
                            st.rerun()
            else:
                # Yeni strateji ekleme paneli
                with st.expander("➕ Yeni Canlı İzleme Stratejisi Ekle", expanded=False):
                    new_strategy_name = st.text_input("Strateji Adı", placeholder="Örn: BTC Trend Takip Stratejisi")

                    selected_model_id_new = st.selectbox(
                        "Sinyal Üretici Olarak Kullanılacak RL Ajanı",
                        options=list(model_options.keys()),
                        format_func=lambda x: model_options[x],
                        key="rl_model_new"
                    )

                    st.write("**Mevcut Kenar Çubuğu Ayarları (RL Ajanı seçilmezse kullanılır):**")
                    st.write(f"- Semboller: `{', '.join(symbols) if symbols else 'Hiçbiri'}`")
                    st.write(f"- Zaman Dilimi: `{interval}`")

                    if st.button("🚀 Yeni Stratejiyi Canlı İzlemeye Al", type="primary"):
                        if not new_strategy_name:
                            st.error("Lütfen stratejiye bir isim verin.")
                        elif not symbols:
                            st.error("Lütfen en az bir sembol seçin.")
                        else:
                            new_strategy = {
                                "id": f"strategy_{int(time.time())}",
                                "name": new_strategy_name,
                                "status": "running",
                                "symbols": symbols,
                                "interval": interval,
                                "strategy_params": strategy_params,
                                "rl_model_id": selected_model_id_new
                            }
                            add_or_update_strategy(new_strategy)
                            st.success(f"'{new_strategy_name}' stratejisi başarıyla eklendi!")
                            st.rerun()

            st.subheader("🏃‍♂️ Çalışan Canlı Stratejiler")
            running_strategies = get_all_strategies()
            if not running_strategies:
                st.info("Şu anda çalışan hiçbir canlı strateji yok.")
            else:
                for strategy in running_strategies:
                    strategy_id = strategy['id']
                    strategy_name = strategy.get('name', 'İsimsiz Strateji')
                    strategy_status = strategy.get('status', 'running')
                    status_emoji = "▶️" if strategy_status == 'running' else "⏸️"
                    is_rl_agent = "🤖" if strategy.get('rl_model_id') else ""

                    with st.expander(
                            f"{status_emoji} **{strategy_name}** {is_rl_agent} (`{strategy.get('interval')}`, `{len(strategy.get('symbols', []))}` sembol)"):
                        live_metrics = get_live_closed_trades_metrics(strategy_id=strategy_id)
                        perf_col1, perf_col2, perf_col3 = st.columns(3)
                        perf_col1.metric("Profit Factor", f"{live_metrics.get('Profit Factor', 0):.2f}")
                        perf_col2.metric("Başarı Oranı", f"{live_metrics.get('Başarı Oranı (%)', 0):.2f}%")
                        perf_col3.metric("Toplam İşlem", f"{live_metrics.get('Toplam İşlem', 0)}")

                        # ... (expander'ın geri kalan içeriği, kontrol butonları vb.)

                        st.caption(f"ID: `{strategy_id}`")
                        st.markdown("---")

                        # --- KONTROL VE AYARLAR (YENİ KOMPAKT TASARIM) ---
                        main_controls_col, trade_settings_col = st.columns([1, 2])

                        # --- Sağ Sütun: Canlı İşlem Ayarları (GÜNCELLENDİ) ---
                        with trade_settings_col:
                            st.markdown("**Canlı İşlem Parametreleri**")
                            params = strategy.get('strategy_params', {})


                            # Fonksiyon artık hangi stratejiyi güncelleyeceğini parametre olarak alıyor
                            def update_trade_params(strategy_to_update):
                                strategy_id_to_update = strategy_to_update['id']

                                new_leverage = st.session_state[f"lev_{strategy_id_to_update}"]
                                new_trade_amount = st.session_state[f"amount_{strategy_id_to_update}"]
                                new_trade_status = st.session_state[f"trade_{strategy_id_to_update}"]
                                new_telegram_status = st.session_state[f"telegram_{strategy_id_to_update}"]

                                updated_params = strategy_to_update.get('strategy_params', {}).copy()
                                updated_params['leverage'] = new_leverage
                                updated_params['trade_amount_usdt'] = new_trade_amount
                                updated_params['telegram_enabled'] = True if new_telegram_status == "Evet" else False

                                strategy_to_update['strategy_params'] = updated_params
                                strategy_to_update[
                                    'is_trading_enabled'] = True if new_trade_status == "Aktif" else False

                                add_or_update_strategy(strategy_to_update)
                                st.toast(f"'{strategy_to_update['name']}' güncellendi!", icon="👍")


                            # Sütunları 4'e çıkarıyoruz
                            trade_cols = st.columns(4)

                            trade_cols[0].slider(
                                "Kaldıraç", 1, 50, params.get('leverage', 5),
                                key=f"lev_{strategy_id}",
                                # kwargs ile doğru stratejiyi fonksiyona iletiyoruz
                                on_change=update_trade_params, kwargs=dict(strategy_to_update=strategy)
                            )
                            trade_cols[1].number_input(
                                "Tutar ($)", min_value=5.0, value=params.get('trade_amount_usdt', 10.0),
                                key=f"amount_{strategy_id}",
                                on_change=update_trade_params, kwargs=dict(strategy_to_update=strategy)
                            )
                            trade_cols[2].radio(
                                "Borsada İşlem", ["Aktif", "Pasif"],
                                index=0 if strategy.get('is_trading_enabled', False) else 1,
                                key=f"trade_{strategy_id}",
                                on_change=update_trade_params, kwargs=dict(strategy_to_update=strategy),
                                horizontal=True
                            )
                            trade_cols[3].radio(
                                "Telegram Bildirim", ["Evet", "Hayır"],
                                index=0 if params.get('telegram_enabled', True) else 1,
                                key=f"telegram_{strategy_id}",
                                on_change=update_trade_params, kwargs=dict(strategy_to_update=strategy),
                                horizontal=True
                            )

                        # --- Sol Sütun: Strateji Kontrolleri ---
                        with main_controls_col:
                            st.markdown("**Strateji Kontrolleri**")
                            control_cols = st.columns(2)

                            # Durdurma / Devam Ettirme Butonları
                            if strategy_status == 'running':
                                control_cols[0].button("⏸️ Durdur", key=f"pause_{strategy_id}",
                                                       use_container_width=True, on_click=update_strategy_status,
                                                       args=(strategy_id, 'paused'))
                            else:
                                control_cols[0].button("▶️ Devam Et", key=f"resume_{strategy_id}",
                                                       use_container_width=True, on_click=update_strategy_status,
                                                       args=(strategy_id, 'running'))

                            # Silme Butonu
                            control_cols[1].button("🗑️ Sil", key=f"stop_{strategy_id}", use_container_width=True,
                                                   help="Stratejiyi tamamen siler.", on_click=remove_strategy,
                                                   args=(strategy_id,))

                            # Ayarları Yükleme ve Düzenleme Butonları
                            st.button("⚙️ Ayarları Tam Düzenle", key=f"edit_{strategy_id}", use_container_width=True,
                                      help="Bu stratejinin tüm ayarlarını düzenlemek için kenar çubuğuna yükler.",
                                      on_click=apply_full_strategy_params, args=(strategy, True))
                            st.button("📥 Ayarları Kenar Çubuğuna Yükle", key=f"load_{strategy_id}",
                                      use_container_width=True, help="Bu stratejinin ayarlarını kenar çubuğuna yükler.",
                                      on_click=apply_full_strategy_params, args=(strategy, False))


        with tab3:
            st.header("🤖 Strateji Koçu")
            # ... (info metni aynı kalacak) ...
            st.info("""
            Bu panel, piyasanın genel durumunu (rejimini) anlık olarak analiz eder ve bu koşullara en uygun
            stratejileri otomatik olarak aktive eder. Uygun olmayan stratejiler ise yeni pozisyon açmamaları
            için yedek kulübesine alınır.
            """)

            if 'orchestrator_log' not in st.session_state:
                st.session_state.orchestrator_log = []

            if st.button("🔄 Orkestratör Döngüsünü Çalıştır", type="primary"):
                with st.spinner("Piyasa rejimi analiz ediliyor..."):
                    result = run_orchestrator_cycle()
                    log_entry = {"time": datetime.now().strftime('%H:%M:%S'), "result": result}
                    st.session_state.orchestrator_log.insert(0, log_entry)
                st.rerun()

            st.subheader("📊 Anlık Piyasa Rejimi")


            # ... (Piyasa rejimi kısmı aynı kalacak) ...
            @st.cache_data(ttl=300)
            def cached_get_market_regime():
                return get_market_regime()


            market_regime = cached_get_market_regime()
            if not market_regime:
                st.error("Piyasa rejimi verisi alınamadı.")
            else:
                cols = st.columns(3)
                cols[0].metric("Piyasa Duygusu", market_regime.get('sentiment', 'Bilinmiyor'))
                cols[1].metric("Trend Gücü", market_regime.get('trend_strength', 'Bilinmiyor'))
                cols[2].metric("Volatilite", market_regime.get('volatility', 'Bilinmiyor'))

            st.markdown("---")
            st.subheader("🎯 Strateji Görev Durumları")

            active_strategies = []
            inactive_strategies = []
            all_strategies = get_all_strategies()
            for strategy in all_strategies:
                dna = get_strategy_dna(strategy['strategy_params'])
                strategy_info = f"**{strategy['name']}** (DNA: `{', '.join(dna)}`)"

                if strategy.get('orchestrator_status', 'active') == 'active':
                    active_strategies.append(strategy_info)
                else:
                    inactive_strategies.append(strategy)  # Stratejinin kendisini listeye ekle

            col1, col2 = st.columns(2)
            with col1:
                st.markdown("<h5>✅ Aktif Görevde</h5>", unsafe_allow_html=True)
                if not active_strategies:
                    st.info("Mevcut rejime uygun aktif strateji bulunmuyor.")
                else:
                    for s_info in active_strategies:
                        st.markdown(f"- {s_info}", unsafe_allow_html=True)

            with col2:
                st.markdown("<h5>⏸️ Yedek Kulübesi</h5>", unsafe_allow_html=True)
                if not inactive_strategies:
                    st.info("Yedekte bekleyen strateji bulunmuyor.")
                else:
                    for strategy in inactive_strategies:
                        with st.container(border=True):
                            info_col, btn_col = st.columns([3, 1])
                            info_col.markdown(f"**{strategy['name']}**")
                            info_col.caption(f"DNA: `{', '.join(get_strategy_dna(strategy['strategy_params']))}`")
                            # --- YENİ BUTON ---
                            if btn_col.button("Aktive Et", key=f"activate_coach_{strategy['id']}",
                                              help="Orkestratör kararını geçersiz kıl ve stratejiyi aktive et."):
                                strategy['orchestrator_status'] = 'active'
                                add_or_update_strategy(strategy)
                                st.toast(f"'{strategy['name']}' manuel olarak aktive edildi!", icon="✅")
                                st.rerun()


            st.subheader("📜 Koç Günlüğü")


        with tab4:
            st.subheader("📊 Anlık Açık Pozisyonlar")
            open_positions_df = get_all_open_positions()

            if open_positions_df.empty:
                st.info("Mevcutta açık pozisyon bulunmuyor.")
            else:
                all_strategies = {s['id']: s for s in get_all_strategies()}

                symbols_for_prices = open_positions_df['Sembol'].unique().tolist()
                live_prices = get_current_prices(symbols_for_prices)

                open_positions_df['Anlık Fiyat'] = open_positions_df['Sembol'].map(live_prices).fillna(0)
                open_positions_df['PnL (%)'] = open_positions_df.apply(
                    lambda row: ((row['Anlık Fiyat'] - row['Giriş Fiyatı']) / row['Giriş Fiyatı']) * 100 if row[
                                                                                                                'Pozisyon'] == 'Long' else (
                        ((row['Giriş Fiyatı'] - row['Anlık Fiyat']) / row['Giriş Fiyatı']) * 100 if row[
                                                                                                        'Giriş Fiyatı'] > 0 else 0),
                    axis=1
                )

                positions_list = open_positions_df.to_dict('records')

                for i in range(0, len(positions_list), 3):
                    col1, col2, col3 = st.columns(3)

                    # --- Birinci Pozisyon Kartı ---
                    with col1:
                        row = positions_list[i]
                        with st.container(border=True):
                            pnl_color = "green" if row['PnL (%)'] >= 0 else "red"
                            emoji = "🟢" if row['Pozisyon'] == 'Long' else "🔴"
                            st.markdown(
                                f"""<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: -0.5rem;"><span style="font-weight: bold;">{emoji} {row['Sembol']}</span><span style="color:{pnl_color}; font-weight: bold;">{row['PnL (%)']:.2f}%</span></div>""",
                                unsafe_allow_html=True)
                            st.caption(f"{row['Strateji Adı']}")

                            strategy_id = row['strategy_id']
                            strategy_config = all_strategies.get(strategy_id, {})
                            current_signal = get_latest_signal(row['Sembol'], strategy_config.get('interval', '1h'),
                                                               strategy_config.get('strategy_params', {}))

                            st.markdown(f"**Pozisyon:** {row['Pozisyon']} | **Sinyal:** {current_signal}")

                            # --- DEĞİŞİKLİK BURADA ---
                            st.markdown(
                                f"<span style='font-size: 100%;'>Giriş: `{row['Giriş Fiyatı']:.4f}` | Anlık: `{row['Anlık Fiyat']:.4f}`</span>",
                                unsafe_allow_html=True)
                            st.markdown(
                                f"<span style='font-size: 100%;'>SL: `{row['Stop Loss']:.4f}` | TP1: `{row['TP1']:.4f}` | TP2: `{row['TP2']:.4f}`</span>",
                                unsafe_allow_html=True)
                            # --- DEĞİŞİKLİK BİTİŞ ---

                            if st.button("Kapat", key=f"close_{row['strategy_id']}_{row['Sembol']}",
                                         use_container_width=True):
                                issue_manual_action(row['strategy_id'], row['Sembol'], 'CLOSE_POSITION')
                                st.toast(f"{row['Sembol']} için kapatma emri gönderildi!", icon="📨")


                    # --- İkinci ve Üçüncü Kartlar ---
                    if i + 1 < len(positions_list):
                        with col2:
                            row = positions_list[i + 1]
                            with st.container(border=True):
                                pnl_color = "green" if row['PnL (%)'] >= 0 else "red"
                                emoji = "🟢" if row['Pozisyon'] == 'Long' else "🔴"
                                st.markdown(
                                    f"""<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: -0.5rem;"><span style="font-weight: bold;">{emoji} {row['Sembol']}</span><span style="color:{pnl_color}; font-weight: bold;">{row['PnL (%)']:.2f}%</span></div>""",
                                    unsafe_allow_html=True)
                                st.caption(f"{row['Strateji Adı']}")
                                strategy_id = row['strategy_id']
                                strategy_config = all_strategies.get(strategy_id, {})
                                current_signal = get_latest_signal(row['Sembol'], strategy_config.get('interval', '1h'),
                                                                   strategy_config.get('strategy_params', {}))
                                st.markdown(f"**Pozisyon:** {row['Pozisyon']} | **Sinyal:** {current_signal}")

                                # --- DEĞİŞİKLİK BURADA ---
                                st.markdown(
                                    f"<span style='font-size: 100%;'>Giriş: `{row['Giriş Fiyatı']:.4f}` | Anlık: `{row['Anlık Fiyat']:.4f}`</span>",
                                    unsafe_allow_html=True)
                                st.markdown(
                                    f"<span style='font-size: 100%;'>SL: `{row['Stop Loss']:.4f}` | TP1: `{row['TP1']:.4f}` | TP2: `{row['TP2']:.4f}`</span>",
                                    unsafe_allow_html=True)
                                # --- DEĞİŞİKLİK BİTİŞ ---

                                if st.button("Kapat", key=f"close_{row['strategy_id']}_{row['Sembol']}",
                                             use_container_width=True):
                                    issue_manual_action(row['strategy_id'], row['Sembol'], 'CLOSE_POSITION')
                                    st.toast(f"{row['Sembol']} için kapatma emri gönderildi!", icon="📨")
                                    time.sleep(1);
                                    st.rerun()

                    if i + 2 < len(positions_list):
                        with col3:
                            row = positions_list[i + 2]
                            with st.container(border=True):
                                pnl_color = "green" if row['PnL (%)'] >= 0 else "red"
                                emoji = "🟢" if row['Pozisyon'] == 'Long' else "🔴"
                                st.markdown(
                                    f"""<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: -0.5rem;"><span style="font-weight: bold;">{emoji} {row['Sembol']}</span><span style="color:{pnl_color}; font-weight: bold;">{row['PnL (%)']:.2f}%</span></div>""",
                                    unsafe_allow_html=True)
                                st.caption(f"{row['Strateji Adı']}")
                                strategy_id = row['strategy_id']
                                strategy_config = all_strategies.get(strategy_id, {})
                                current_signal = get_latest_signal(row['Sembol'], strategy_config.get('interval', '1h'),
                                                                   strategy_config.get('strategy_params', {}))
                                st.markdown(f"**Pozisyon:** {row['Pozisyon']} | **Sinyal:** {current_signal}")

                                # --- DEĞİŞİKLİK BURADA ---
                                st.markdown(
                                    f"<span style='font-size: 100%;'>Giriş: `{row['Giriş Fiyatı']:.4f}` | Anlık: `{row['Anlık Fiyat']:.4f}`</span>",
                                    unsafe_allow_html=True)
                                st.markdown(
                                    f"<span style='font-size: 100%;'>SL: `{row['Stop Loss']:.4f}` | TP1: `{row['TP1']:.4f}` | TP2: `{row['TP2']:.4f}`</span>",
                                    unsafe_allow_html=True)
                                # --- DEĞİŞİKLİK BİTİŞ ---

                                if st.button("Kapat", key=f"close_{row['strategy_id']}_{row['Sembol']}",
                                             use_container_width=True):
                                    issue_manual_action(row['strategy_id'], row['Sembol'], 'CLOSE_POSITION')
                                    st.toast(f"{row['Sembol']} için kapatma emri gönderildi!", icon="📨")
                                    time.sleep(1);
                                    st.rerun()

        # Sekme 5: Alarm Geçmişi
        with tab5:
            st.subheader("🔔 Son Alarmlar")
            st.info("Tüm stratejilerden gelen, pozisyon açma/kapama ve diğer önemli olayları içeren kayıt defteri.")
            alarm_history = get_alarm_history_db(limit=100)
            if alarm_history is not None and not alarm_history.empty:
                st.dataframe(alarm_history, use_container_width=True, height=600)
            else:
                st.info("Veritabanında henüz kayıtlı bir alarm yok.")

        # app.py dosyasındaki "with tab6:" ile başlayan mevcut bloğu silip bunu yapıştırın

        with tab6:
            st.header("🧬 Strateji Gen Havuzu ve Evrimsel Optimizasyon")
            st.info("""
               Bu panel, strateji ekosisteminizi yönetmenizi sağlar. Sistem, en iyi performans gösteren stratejileri
               seçip onları "çaprazlayarak" veya "mutasyona uğratarak" yeni nesiller yaratır. En kötü performans
               gösterenler ise doğal seçilim yoluyla **duraklatılır**. Sizin rolünüz, bu evrim sürecini yönetmek ve 
               duraklatılan stratejileri inceleyip isterseniz kalıcı olarak silmektir.
               """)

            if 'evolution_log' not in st.session_state:
                st.session_state.evolution_log = []

            if st.button("🚀 Evrim Döngüsünü Başlat", type="primary"):
                with st.spinner("Evrim döngüsü çalışıyor..."):
                    result = run_evolution_cycle()
                    log_entry = {"time": datetime.now().strftime('%H:%M:%S'), "result": result}
                    st.session_state.evolution_log.insert(0, log_entry)
                st.rerun()

            st.subheader("📈 Canlı Strateji Performans Lider Tablosu")

            all_strategies = get_all_strategies()
            strategy_performance_data = []
            paused_strategies = []

            for strategy in all_strategies:
                if strategy.get('status') == 'paused':
                    paused_strategies.append(strategy)
                    continue  # Duraklatılanları lider tablosunda gösterme

                metrics = get_live_closed_trades_metrics(strategy_id=strategy['id'])
                performance_score = metrics.get('Profit Factor', 0)
                if performance_score == float('inf'): performance_score = 1000

                strategy_performance_data.append({
                    "Strateji Adı": strategy['name'],
                    "Profit Factor": f"{performance_score:.2f}",
                    "Başarı Oranı (%)": f"{metrics.get('Başarı Oranı (%)', 0):.2f}",
                    "Toplam İşlem": metrics.get('Toplam İşlem', 0),
                })

            if not strategy_performance_data:
                st.info("Gösterilecek aktif strateji bulunamadı.")
            else:
                df_performance = pd.DataFrame(strategy_performance_data)
                df_performance['Profit Factor'] = pd.to_numeric(df_performance['Profit Factor'])
                df_performance = df_performance.sort_values(by="Profit Factor", ascending=False).reset_index(drop=True)
                st.dataframe(df_performance, use_container_width=True)

            st.markdown("---")

            # --- YENİ BÖLÜM: Duraklatılan Stratejiler ---
            st.subheader("⏸️ Duraklatılan Stratejiler (İnceleme Bekleyenler)")
            if not paused_strategies:
                st.info("Düşük performans nedeniyle duraklatılmış bir strateji bulunmuyor.")
            else:
                st.warning(
                    "Aşağıdaki stratejiler, Evrim Döngüsü tarafından düşük performanslı olarak işaretlendi ve duraklatıldı.")
                for strategy in paused_strategies:
                    with st.container(border=True):
                        # --- DEĞİŞİKLİK BURADA ---
                        col1, col2, col3 = st.columns([3, 1, 1])
                        with col1:
                            st.markdown(f"**{strategy['name']}**")
                            st.caption(f"ID: `{strategy['id']}`")
                        with col2:
                            # --- YENİ BUTON ---
                            if st.button("✅ Aktive Et", key=f"activate_evo_{strategy['id']}"):
                                update_strategy_status(strategy['id'], 'running')
                                st.toast(f"'{strategy['name']}' tekrar aktive edildi!", icon="✅")
                                st.rerun()
                        with col3:
                            if st.button("🗑️ Sil", key=f"delete_paused_{strategy['id']}", type="primary"):
                                remove_strategy(strategy['id'])
                                st.toast(f"'{strategy['name']}' kalıcı olarak silindi!", icon="🗑️")
                                st.rerun()

            # ... (Evrim döngüsü günlüğü aynı kalacak) ...
            st.subheader("📜 Evrim Döngüsü Günlüğü")
            if not st.session_state.evolution_log:
                st.info("Henüz bir evrim döngüsü çalıştırılmadı.")
            else:
                for log in st.session_state.evolution_log:
                    with st.expander(
                            f"Döngü Zamanı: {log['time']} - Durum: {log['result'].get('status', 'Bilinmiyor').capitalize()}"):
                        result = log['result']
                        if result['status'] == 'completed':
                            st.markdown("**Duraklatılan Stratejiler:**")
                            for name in result.get('eliminated', []):
                                st.markdown(f"- ⏸️ `{name}`")
                            st.markdown("**Oluşturulan Yeni Stratejiler:**")
                            for name in result.get('created', []):
                                st.markdown(f"- ✨ `{name}`")
                        else:
                            st.warning(f"Bu döngü atlandı. Sebep: {result.get('reason', 'Bilinmiyor')}")

        with tab7:
            st.header("🤖 Kendi Kendine Öğrenen Ticaret Ajanı")
            st.info("""
                Bu bölümde, Pekiştirmeli Öğrenme (RL) teknolojisini kullanarak kendi ticaret stratejisini sıfırdan öğrenen
                bir yapay zeka ajanını eğitebilir ve performansını test edebilirsiniz. Ajan, geçmiş veriler üzerinde
                milyonlarca işlem yaparak kârını maksimize etmeyi öğrenir.
                """)

            st.subheader("1. Ajanı Eğit")
            col1, col2, col3 = st.columns(3)
            with col1:
                rl_symbol = st.selectbox("Eğitim için Sembol", options=st.session_state.get('symbols_key', ["BTCUSDT"]))
            with col2:
                rl_interval = st.selectbox("Eğitim için Zaman Dilimi", options=["15m", "1h", "4h"], index=1)
            with col3:
                rl_timesteps = st.number_input("Eğitim Adım Sayısı", min_value=1000, max_value=100000, value=25000,
                                               step=1000)

            if st.button("🚀 Ajan Eğitimini Başlat", type="primary"):
                with st.spinner(
                        f"Lütfen bekleyin... RL ajanı **{rl_symbol}** verileri üzerinde **{rl_timesteps}** adım boyunca eğitiliyor..."):
                    train_rl_agent(symbol=rl_symbol, interval=rl_interval, total_timesteps=rl_timesteps)
                st.success("Eğitim başarıyla tamamlandı! Eğitilmiş model veritabanına kaydedildi.")
                st.balloons()
                st.rerun()

            st.markdown("---")

            st.subheader("2. Eğitilmiş Ajanı Test Et (Backtest)")

            st.session_state.rl_models_list = get_all_rl_models_info()
            if not st.session_state.rl_models_list:
                st.warning("Henüz veritabanında kayıtlı bir model bulunmuyor. Lütfen önce bir ajan eğitin.")
            else:
                model_options_test = {
                    model['id']: f"{model['name']} (Eğitim: {model['created_at'].strftime('%Y-%m-%d %H:%M')})" for model
                    in st.session_state.rl_models_list}
                selected_model_id_test = st.selectbox(
                    "Test edilecek eğitilmiş modeli seçin",
                    options=model_options_test.keys(),
                    format_func=lambda x: model_options_test[x]
                )

                if st.button("📈 RL Ajanı ile Backtest Yap"):
                    model_info = next((m for m in st.session_state.rl_models_list if m['id'] == selected_model_id_test),
                                      None)
                    if model_info:
                        model_symbol = model_info['name'].split('_')[1]
                        model_interval = model_info['name'].split('_')[2]

                        with st.spinner(
                                f"Backtest verisi ({model_symbol}/{model_interval}) indiriliyor ve model yükleniyor..."):
                            backtest_df_raw = get_binance_klines(symbol=model_symbol, interval=model_interval,
                                                                 limit=1000)

                        if not backtest_df_raw.empty:
                            with st.spinner("Model, geçmiş veriler üzerinde işlem yapıyor..."):
                                trades_df, backtest_df_with_actions = run_rl_backtest(selected_model_id_test,
                                                                                      backtest_df_raw)

                            st.success("RL Ajanı Backtesti tamamlandı!")
                            st.session_state.rl_trades_df = trades_df
                            st.session_state.rl_backtest_df = backtest_df_with_actions
                            st.rerun()
                        else:
                            st.error("Backtest için veri indirilemedi.")

            # Sonuçları göstermek için ayrı bir bölüm
            if 'rl_trades_df' in st.session_state and st.session_state.rl_trades_df is not None:
                st.markdown("---")
                st.subheader("📊 RL Ajanı Backtest Sonuçları")

                trades_df = st.session_state.rl_trades_df
                backtest_df = st.session_state.rl_backtest_df

                if trades_df.empty:
                    st.info("Ajan bu periyotta hiç işlem yapmadı.")
                else:
                    performance_metrics, equity_curve, drawdown_series = analyze_backtest_results(trades_df)
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("Toplam Kâr/Zarar (%)", f"{performance_metrics.get('Toplam Getiri (%)', 0):.2f}%")
                        st.metric("Başarı Oranı (%)", f"{performance_metrics.get('Kazançlı İşlem Oranı (%)', 0):.2f}%")
                    with col2:
                        st.metric("Toplam İşlem Sayısı", f"{performance_metrics.get('Toplam İşlem', 0)}")
                        st.metric("Maksimum Düşüş (Drawdown)",
                                  f"{performance_metrics.get('Maksimum Düşüş (Drawdown) (%)', 0):.2f}%")

                    st.subheader("🤖 Ajan Karar Grafiği")
                    st.info(
                        "Grafik üzerindeki Mavi (Yukarı) ve Pembe (Aşağı) üçgenler, RL Ajanı'nın Al/Sat kararlarını göstermektedir.")

                    chart_options = {"show_sma": True, "show_ema": True}
                    fig = plot_chart(backtest_df, backtest_df.attrs.get('symbol', ''), {}, chart_options,
                                     rl_signal_col='RL_Signal')
                    st.plotly_chart(fig, use_container_width=True)

                    st.subheader("📈 Sermaye Eğrisi ve Düşüş Grafiği")
                    if equity_curve is not None:
                        performance_fig = plot_performance_summary(equity_curve, drawdown_series)
                        st.plotly_chart(performance_fig, use_container_width=True)

                    st.subheader("📋 İşlem Listesi")
                    st.dataframe(trades_df, use_container_width=True)

elif page == "🧪 Deney Odası":
    st.header("⚙️ Strateji Parametre Optimizasyonu")
    st.info("""
    Bu bölümde, stratejinizin en iyi performans gösteren parametrelerini bulmak için binlerce kombinasyonu test edebilirsiniz.
    Lütfen optimize etmek istediğiniz hedefi ve parametrelerin test edileceği aralıkları seçin.
    """)

    st.subheader("1. Optimizasyon Hedefini Seçin")
    optimization_target = st.selectbox(
        "Hangi Metriğe Göre Optimize Edilsin?",
        options=["Sharpe Oranı (Yıllık)", "Sortino Oranı (Yıllık)", "Calmar Oranı", "Maksimum Düşüş (Drawdown) (%)",
                 "Toplam Getiri (%)"],
        index=0,
        help="Optimizasyon, seçtiğiniz bu metriği maksimize (veya Drawdown için minimize) etmeye çalışacaktır."
    )

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
            current_params = strategy_params.copy()
            current_params.update(params_to_test)

            current_params['stop_loss_pct'] = 0

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

                trades_df = backtest_signals(df)
                if not trades_df.empty:
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
            status_text.text(
                f"Test {i + 1}/{len(test_combinations)} tamamlandı. En iyi {optimization_target}: {st.session_state.get('best_score', 'N/A')}")

        if results_list:
            results_df = pd.DataFrame(results_list)

            is_ascending = True if optimization_target == "Maksimum Düşüş (Drawdown) (%)" else False
            sorted_results = results_df.sort_values(by=optimization_target, ascending=is_ascending).head(10)

            st.session_state.best_score = f"{sorted_results.iloc[0][optimization_target]:.2f}"
            st.session_state.optimization_results = sorted_results

        status_text.success("✅ Optimizasyon tamamlandı! En iyi 10 sonuç aşağıda listelenmiştir.")

    if 'optimization_results' in st.session_state and not st.session_state.optimization_results.empty:
        st.subheader("🏆 En İyi Parametre Kombinasyonları")
        results_df = st.session_state.optimization_results

        display_cols = [
            'rsi_buy', 'rsi_sell', 'adx_threshold', 'atr_multiplier', 'take_profit_pct',
            optimization_target, 'Toplam İşlem', 'Kazançlı İşlem Oranı (%)'
        ]
        display_cols_exist = [col for col in display_cols if col in results_df.columns]
        st.dataframe(results_df[display_cols_exist])

        st.subheader("4. Sonuçları Kenar Çubuğuna Aktar")

        selected_index = st.selectbox(
            "Uygulamak istediğiniz sonucun index'ini seçin:",
            results_df.index,
            help="Yukarıdaki tablodan en beğendiğiniz sonucun index numarasını seçin."
        )

        st.button(
            "✅ Seçili Parametreleri Uygula",
            on_click=apply_selected_params,
            args=(results_df.loc[selected_index],)
        )

elif page == "📊 Simülasyon":
    st.header("📈 Portföy Backtest ve Detaylı Analiz")

    # Sekmeli yapıyı oluştur
    tab1, tab2 = st.tabs(["📊 Backtest Sonuçları", "📈 Detaylı Grafik Analizi"])

    # Sekme 1: Backtest Sonuçları
    with tab1:
        st.info(
            "Bu bölümde, kenar çubuğunda belirlediğiniz stratejiyi seçtiğiniz semboller üzerinde test edebilir ve genel performans metriklerini görebilirsiniz.")

        st.session_state.selected_symbols = symbols

        if st.button("🚀 Portföy Backtest Başlat"):
            run_portfolio_backtest(symbols, interval, strategy_params)

        if 'backtest_results' in st.session_state and not st.session_state['backtest_results'].empty:
            portfolio_results = st.session_state['backtest_results'].copy()
            analysis_df = portfolio_results.dropna(subset=['Çıkış Zamanı'])

            if not analysis_df.empty:
                performance_metrics, equity_curve, drawdown_series = analyze_backtest_results(analysis_df)
                st.subheader("📊 Portföy Performans Metrikleri")
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

                col1, col2 = st.columns(2)
                metrics_list = list(performance_metrics.items())
                mid_point = (len(metrics_list) + 1) // 2

                with col1:
                    for key, value in metrics_list[:mid_point]:
                        st.metric(label=key, value=value, help=metric_tooltips.get(key, ""))
                with col2:
                    for key, value in metrics_list[mid_point:]:
                        st.metric(label=key, value=value, help=metric_tooltips.get(key, ""))

                st.subheader("📈 Strateji Performans Grafiği")
                if equity_curve is not None and drawdown_series is not None:
                    performance_fig = plot_performance_summary(equity_curve, drawdown_series)
                    st.plotly_chart(performance_fig, use_container_width=True)

            st.subheader("📋 Tüm İşlemler")
            st.dataframe(portfolio_results, use_container_width=True)
        else:
            st.info("Backtest sonuçları burada görünecek. Lütfen 'Portföy Backtest Başlat' butonuna basın.")

    # Sekme 2: Detaylı Grafik Analizi
    with tab2:
        st.info("""
        Bu bölümde, yukarıdaki "Backtest Sonuçları" sekmesinde çalıştırdığınız son testin sonuçlarını sembol bazında detaylı olarak inceleyebilirsiniz.
        Grafik üzerindeki göstergeleri kenar çubuğundaki **"📊 Grafik Gösterge Seçenekleri"** menüsünden kontrol edebilirsiniz.
        """)

        if 'backtest_data' not in st.session_state or not st.session_state.backtest_data:
            st.warning("Lütfen önce 'Backtest Sonuçları' sekmesinden bir backtest çalıştırın.")
        else:
            backtested_symbols = list(st.session_state.backtest_data.keys())
            selected_symbol = st.selectbox("Analiz edilecek sembolü seçin:", backtested_symbols)

            if selected_symbol:
                df_chart = st.session_state.backtest_data[selected_symbol]
                chart_options = {
                    "show_sma": show_sma, "show_ema": show_ema, "show_bbands": show_bbands,
                    "show_vwap": show_vwap, "show_adx": show_adx, "show_stoch": show_stoch,
                    "show_fibonacci": show_fibonacci
                }
                fib_levels = calculate_fibonacci_levels(df_chart) if show_fibonacci else {}
                fig = plot_chart(df_chart, selected_symbol, fib_levels, chart_options)
                st.plotly_chart(fig, use_container_width=True)

