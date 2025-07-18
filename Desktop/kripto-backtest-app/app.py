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
    else:
        forward_window = None
        target_thresh = None

st.sidebar.header("🔔 Sinyal Kriterleri Seçenekleri")
col1, col2 = st.sidebar.columns(2)
use_rsi = col1.checkbox("RSI Sinyali", value=True)
use_macd = col2.checkbox("MACD Sinyali", value=True)

col3, col4 = st.sidebar.columns(2)
use_bb = col3.checkbox("Bollinger Sinyali", value=True)
use_adx = col4.checkbox("ADX Sinyali", value=True)

adx_threshold = st.sidebar.slider("ADX Eşiği", 10, 50, 25)

with st.sidebar.expander("📊 Teknik Gösterge Parametreleri", expanded=False):
    rsi_period = st.number_input("RSI Periyodu", value=14, min_value=2)
    macd_fast = st.number_input("MACD Fast", value=12, min_value=1)
    macd_slow = st.number_input("MACD Slow", value=26, min_value=1)
    macd_signal = st.number_input("MACD Signal", value=9, min_value=1)
    adx_period = st.number_input("ADX Periyodu", value=14, min_value=2)

# Üst ekran sembol ve interval seçimi (sabit)
symbols = st.multiselect(
    "📈 Portföyde test edilecek semboller",
    [
        "BTCUSDT", "ETHUSDT", "BNBUSDT",  "XRPUSDT", "SOLUSDT", "ADAUSDT", "DOGEUSDT",
        "MATICUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT", "SHIBUSDT", "AVAXUSDT", "UNIUSDT",
        "LINKUSDT", "ALGOUSDT", "ATOMUSDT", "BCHUSDT", "XLMUSDT", "VETUSDT", "FILUSDT",
        "ICPUSDT", "THETAUSDT", "EOSUSDT", "AAVEUSDT", "MKRUSDT", "KSMUSDT", "XTZUSDT",
        "NEARUSDT", "CAKEUSDT", "FTMUSDT", "GRTUSDT", "SNXUSDT", "RUNEUSDT", "CHZUSDT",
        "ZILUSDT", "DASHUSDT", "SANDUSDT", "KAVAUSDT", "COMPUSDT", "LUNAUSDT", "ENJUSDT",
        "BATUSDT", "NANOUSDT", "1INCHUSDT", "ZRXUSDT", "CELRUSDT", "HNTUSDT", "FTTUSDT",
        "GALAUSDT"
    ],
    default=["BTCUSDT", "ETHUSDT", "BNBUSDT",  "XRPUSDT", "SOLUSDT", "ADAUSDT", "DOGEUSDT","MATICUSDT", "DOTUSDT", "LTCUSDT", "TRXUSDT"]
)

interval = st.selectbox("⏳ Zaman Dilimi Seçin", options=["15m", "1h", "4h"], index=1)

# Container’lar
results_section = st.container()
optimize_section = st.container()

st.header("⚙️ Strateji Gelişmiş Ayarlar")

col1, col2, col3, col4 = st.columns(4)

with col1:
    signal_mode = st.selectbox("Sinyal Modu", ["Long Only", "Long & Short"], index=1)

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
    'use_rsi': use_rsi,
    'rsi_buy': rsi_buy,
    'rsi_sell': rsi_sell,
    'use_macd': use_macd,
    'use_bb': use_bb,
    'use_adx': use_adx,
    'adx': adx_threshold,
    'signal_mode': signal_mode,
    'stop_loss_pct': stop_loss_pct,
    'take_profit_pct': take_profit_pct,
    'cooldown_bars': cooldown_bars,
    'use_puzzle_bot': use_puzzle_bot,
    'use_ml': use_ml,
    'forward_window': forward_window,
    'target_thresh': target_thresh,
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

            df_temp = generate_all_indicators(df_latest,
                                              sma_period=st.session_state.get('sma_period', 50),
                                              ema_period=st.session_state.get('ema_period', 20),
                                              bb_period=st.session_state.get('bb_period', 20),
                                              bb_std=st.session_state.get('bb_std', 2.0))

            df_temp = generate_signals(df_temp,
                                       use_rsi=st.session_state.get('use_rsi', True),
                                       rsi_buy=st.session_state.get('rsi_buy', 30),
                                       rsi_sell=st.session_state.get('rsi_sell', 70),
                                       use_macd=st.session_state.get('use_macd', True),
                                       use_bb=st.session_state.get('use_bb', True),
                                       use_adx=st.session_state.get('use_adx', True),
                                       adx_threshold=st.session_state.get('adx', 25),
                                       signal_mode=st.session_state.get('signal_mode', "Long Only"),
                                       use_puzzle_bot=st.session_state.get('use_puzzle_bot', False))

            last_price = df_latest['Close'].iloc[-1]
            last_signal = df_temp['Signal'].iloc[-1]

            if st.session_state.get('use_telegram', False) and last_signal != last_signal_sent and last_signal != "Bekle":
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
    for symbol in symbols:
        st.write(f"🔍 {symbol} verisi indiriliyor ve strateji uygulanıyor...")
        df = get_binance_klines(symbol=symbol, interval=interval)
        if df is not None and not df.empty:
            df = generate_all_indicators(
                df,
                sma_period=strategy_params['sma'],
                ema_period=strategy_params['ema'],
                bb_period=strategy_params['bb_period'],
                bb_std=strategy_params['bb_std']
            )
            df = generate_signals(
                df,
                use_rsi=strategy_params['use_rsi'],
                use_macd=strategy_params['use_macd'],
                use_bb=strategy_params['use_bb'],
                use_adx=strategy_params['use_adx'],
                use_puzzle_bot=strategy_params['use_puzzle_bot'],
                signal_mode=strategy_params['signal_mode']
            )
            df = create_signal_column(df)

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
                                             use_adx=params.get('use_adx', True),
                                             adx_threshold=params.get('adx', 25),
                                             signal_mode=params.get('signal_mode', "Long Only"),
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
                # Hata loglanabilir
                pass
        time.sleep(delay)


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
            if df is None or df.empty:
                continue
            df = generate_all_indicators(df, sma_period=50, ema_period=20, bb_period=bb_p, bb_std=bb_st)
            df = generate_signals(df, use_rsi=True, use_macd=True, use_bb=True, use_adx=True,
                                  rsi_buy=rsi_b, rsi_sell=rsi_s, adx_threshold=25, signal_mode="Long Only")
            results = backtest_signals(df)
            if results is not None and not results.empty:
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
# Ana Sayfa Menü Yönetimi

if page == "Portföy Backtest":
    st.header("🚀 Portföy Backtest")

    # ✅ 2. Session state'e sembolleri kaydet (buraya ekle)
    st.session_state.selected_symbols = symbols

    if st.button("Portföy Backtest Başlat"):
        run_portfolio_backtest(symbols, interval, strategy_params)

    # Backtest sonuçları varsa göster
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

    # Başlangıç durumu kontrolü
    if "live_tracking" not in st.session_state:
        st.session_state.live_tracking = False

    # ⏺️ Durum Göstergesi
    if st.session_state.live_tracking:
        st.success("🔔 Durum: Sinyal İzleniyor")
    else:
        st.warning("⏹️ Durum: İzleme Kapalı")

    # Sembol girişi yerine session_state kullan (Backtest sayfasında girilen semboller)
    if "selected_symbols" in st.session_state:
        symbols = st.session_state.selected_symbols
        st.markdown(f"**🎯 İzlenen Semboller:** {', '.join(symbols)}")
    else:
        st.error("ℹ️ Lütfen önce Ana Sayfadan sembolleri girin ve Backtest yapın.")

    # ▶️ Başlat / ⏹️ Durdur butonları
    col1, col2 = st.columns(2)
    if col1.button("▶️ Başlat"):
        if "selected_symbols" in st.session_state:
            st.session_state.live_tracking = True
            # Burada canlı izleme fonksiyonunu çağırabilirsin
            # örn: start_live_signal_tracking(st.session_state.selected_symbols)
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
        st.success(f"Optimizasyon tamamlandı! En iyi parametreler: RSI Al={best_params[0]}, RSI Sat={best_params[1]}, BB Periyodu={best_params[2]}, BB Std={best_params[3]} - Ortalama Getiri: {best_score:.2f}%")

    st.info("Optimizasyon büyük veri indirme gerektirir, lütfen sabırlı olun.")

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
