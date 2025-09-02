
import json
import time
import threading
import pandas as pd
import websocket
import os
import sys
import signal
import logging
import traceback
from datetime import datetime
from stable_baselines3 import PPO
import numpy as np
from trade_executor import set_futures_leverage_and_margin, place_futures_order, get_open_position_amount, \
    get_symbol_info, place_futures_stop_market_order, place_futures_take_profit_order

from utils import get_binance_klines
from indicators import generate_all_indicators

from signals import generate_signals, add_higher_timeframe_trend, filter_signals_with_trend
from telegram_alert import send_telegram_message
from database import (
    initialize_db, get_all_strategies, update_position,
    get_positions_for_strategy, log_alarm_db,
    get_and_clear_pending_actions,get_rl_model_by_id
)
from trading_env import TradingEnv

# --- Loglama Yapılandırması ---
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler("multi_worker.log"),
                        logging.StreamHandler()
                    ])

# --- Lock File Mekanizması ---
try:
    project_dir = os.path.dirname(os.path.abspath(__file__))
    LOCK_FILE = os.path.join(project_dir, "multi_worker.lock")
except Exception:
    LOCK_FILE = "multi_worker.lock"


def create_lock_file():
    if os.path.exists(LOCK_FILE):
        return False
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True


def remove_lock_file():
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
            logging.info("✅ Kilit dosyası başarıyla kaldırıldı.")
        except OSError as e:
            logging.warning(f"⚠️ Kilit dosyası kaldırılamadı: {e}")


def graceful_shutdown(signum, frame):
    logging.info(f"\n🛑 Kapanma sinyali ({signum}) alındı. Tüm işlemler durduruluyor...")
    sys.exit(0)


class StrategyRunner:
    def __init__(self, strategy_config):
        self.config = strategy_config
        self.id = strategy_config['id']
        self.name = strategy_config['name']
        self.symbols = strategy_config['symbols']
        self.interval = strategy_config['interval']
        self.last_prices = {}
        self.symbols_to_track = strategy_config['symbols']
        raw_params = strategy_config.get('strategy_params', {})
        if isinstance(raw_params, str):
            try:
                self.params = json.loads(raw_params)
            except json.JSONDecodeError:
                self.params = {}
        else:
            self.params = raw_params

        self.portfolio_data = {}
        self.ws_threads = {}
        self._stop_event = threading.Event()
        self.position_locks = {symbol: threading.Lock() for symbol in self.symbols}

        # --- YENİ: RL Modelini Veritabanından Yükleme ---
        self.rl_model = None
        # Stratejiye bağlı modelin ID'sini al
        rl_model_id = self.config.get('rl_model_id')
        if rl_model_id:
            try:
                logging.info(f"🤖 RL AJANI VERİTABANINDAN YÜKLENİYOR ({self.name}): Model ID = {rl_model_id}")
                # Modeli veritabanından byte olarak çek
                model_buffer = get_rl_model_by_id(rl_model_id)
                if model_buffer:
                    # Gelen byte verisinden modeli yükle
                    self.rl_model = PPO.load(model_buffer)
                    logging.info(f"✅ RL Ajanı (ID: {rl_model_id}) başarıyla yüklendi: '{self.name}'")
                else:
                    logging.error(f"❌ HATA ({self.name}): Veritabanında RL Ajanı (ID: {rl_model_id}) bulunamadı.")
            except Exception as e:
                logging.error(f"❌ KRİTİK HATA ({self.name}): RL Ajanı (ID: {rl_model_id}) yüklenemedi: {e}")
                self.rl_model = None

        self._load_positions()

    def _load_positions(self):
        try:
            # Veritabanından pozisyonları tam detaylarıyla yükle
            loaded_positions = get_positions_for_strategy(self.id)
            for symbol, pos_data in loaded_positions.items():
                # Başlangıçta hafızayı doldur
                self.portfolio_data[symbol] = {
                    'position': pos_data.get('position'),
                    'entry_price': pos_data.get('entry_price', 0),
                    'df': self.portfolio_data.get(symbol, {}).get('df'),  # Mevcut DataFrame'i koru
                    'last_signal': None
                }
            logging.info(f"BİLGİ ({self.name}): Veritabanından başlangıç pozisyonları yüklendi.")
        except Exception as e:
            logging.error(f"HATA ({self.name}): Veritabanından pozisyonlar okunurken hata: {e}")
            self.portfolio_data = {}

    def start(self):
        logging.info(f"✅ Strateji BAŞLATILIYOR: '{self.name}' (ID: {self.id})")
        action_checker_thread = threading.Thread(target=self._check_manual_actions, daemon=True)
        action_checker_thread.start()
        for symbol in self.symbols:
            try:
                initial_df = get_binance_klines(symbol, self.interval, limit=200)
                if initial_df is None or initial_df.empty:
                    logging.warning(f"HATA ({self.name}): {symbol} için başlangıç verisi alınamadı. Atlanıyor.")
                    continue
                if symbol not in self.portfolio_data:
                    self.portfolio_data[symbol] = {
                        'position': None, 'entry_price': 0, 'stop_loss_price': 0,
                        'tp1_price': 0, 'tp2_price': 0, 'tp1_hit': False, 'tp2_hit': False,
                        'last_signal': None
                    }
                self.portfolio_data[symbol]['df'] = initial_df
                ws_thread = threading.Thread(target=self._run_websocket, args=(symbol,), daemon=True)
                self.ws_threads[symbol] = ws_thread
                ws_thread.start()
                time.sleep(0.5)
            except Exception as e:
                logging.critical(f"KRİTİK HATA ({self.name}): {symbol} başlatılırken sorun: {e}")

    def stop(self):
        logging.info(f"🛑 Strateji DURDURULUYOR: '{self.name}' (ID: {self.id})")
        self._stop_event.set()

    # multi_worker.py içindeki _close_position fonksiyonunu bununla değiştirin

    def _close_position(self, symbol: str, close_price: float, reason: str, size_pct_to_close: float = 100.0):
        """
        Pozisyonun belirtilen yüzdesini kapatır ve durumu doğru bir şekilde günceller.
        size_pct_to_close: 1.0 ile 100.0 arasında bir değer.
        """
        symbol_data = self.portfolio_data.get(symbol, {})
        current_position = symbol_data.get('position')
        entry_price = symbol_data.get('entry_price', 0)
        if not current_position:
            return

        with self.position_locks[symbol]:
            is_trading_enabled = self.config.get('is_trading_enabled', False)

            # --- POZİSYON KAPATMA EMİRLERİ (SADECE CANLI İŞLEM AÇIKSA) ---
            if is_trading_enabled:
                total_quantity = get_open_position_amount(symbol)
                if total_quantity > 0:
                    quantity_to_close = total_quantity * (size_pct_to_close / 100.0)
                    symbol_info = get_symbol_info(symbol)
                    if symbol_info:
                        quantity_precision = int(symbol_info['quantityPrecision'])
                        quantity_to_close = round(quantity_to_close, quantity_precision)
                    if quantity_to_close > 0:
                        close_side = 'SELL' if current_position == 'Long' else 'BUY'
                        place_futures_order(symbol, close_side, quantity_to_close)

            # --- POZİSYONUN DAHLİ DURUMUNU GÜNCELLE (HER ZAMAN) ---
            # Kar/Zarar (P&L) hesaplaması ve loglama
            pnl = ((close_price - entry_price) / entry_price * 100) if current_position == 'Long' else (
                    (entry_price - close_price) / entry_price * 100)
            log_reason = f"{reason} ({size_pct_to_close}%)"
            self.notify_and_log(symbol, log_reason, close_price, pnl)

            # Hafızayı ve veritabanı durumunu güncelle
            if size_pct_to_close >= 100.0:
                self._reset_position_state(symbol)
            else:
                # --- DÜZELTİLMİŞ GÜNCELLEME MANTIĞI ---
                # Stale (eski) veri kullanmamak için pozisyonun en güncel halini veritabanından çek
                current_state_from_db = get_positions_for_strategy(self.id).get(symbol, {})
                if not current_state_from_db:  # Güvenlik kontrolü
                    current_state_from_db = self.portfolio_data.get(symbol, {})

                new_tp1_hit = current_state_from_db.get('tp1_hit', False)
                new_tp2_hit = current_state_from_db.get('tp2_hit', False)

                if "Take-Profit 1" in reason:
                    new_tp1_hit = True
                elif "Take-Profit 2" in reason:
                    new_tp2_hit = True

                # Veritabanını yeni bayraklarla güncelle
                update_position(self.id, symbol, current_state_from_db.get('position'), current_state_from_db.get('entry_price'),
                                sl_price=current_state_from_db.get('stop_loss_price'),
                                tp1_price=current_state_from_db.get('tp1_price'),
                                tp2_price=current_state_from_db.get('tp2_price'),
                                tp1_hit=new_tp1_hit,
                                tp2_hit=new_tp2_hit)

                # Yerel hafızayı da senkronize et (isteğe bağlı ama iyi bir pratik)
                if symbol in self.portfolio_data:
                    self.portfolio_data[symbol]['tp1_hit'] = new_tp1_hit
                    self.portfolio_data[symbol]['tp2_hit'] = new_tp2_hit

    def _check_manual_actions(self):
        while not self._stop_event.is_set():
            try:
                actions = get_and_clear_pending_actions(self.id)
                for action in actions:
                    if action['action'] == 'CLOSE_POSITION':
                        symbol_to_close = action['symbol']
                        logging.info(
                            f"MANUEL KOMUT ({self.name}): {symbol_to_close} için pozisyon kapatma emri alındı.")
                        self._close_position_manually(symbol_to_close)
            except Exception as e:
                logging.error(f"HATA ({self.name}): Manuel komutlar kontrol edilirken hata: {e}")
            time.sleep(5)

        # multi_worker.py dosyasındaki StrategyRunner sınıfının içine ekleyin

    def _close_position_manually(self, symbol):
            """
            Manuel kapatma emrini işler.
            """
            if not self.portfolio_data.get(symbol, {}).get('position'):
                logging.info(f"BİLGİ ({self.name}): {symbol} için kapatılacak aktif pozisyon bulunamadı.")
                return
            try:
                # Fiyat verisini alırken boş DataFrame kontrolü ekle
                df_latest = get_binance_klines(symbol, self.interval, limit=1)
                if df_latest.empty:
                    logging.error(f"HATA ({self.name}): Manuel kapatma için {symbol} anlık fiyatı alınamadı: Boş veri.")
                    return

                latest_price = df_latest.iloc[-1]['Close']
                self._close_position(symbol, latest_price, "Manuel Kapatma")
            except Exception as e:
                logging.error(f"HATA ({self.name}): Manuel kapatma için {symbol} anlık fiyatı alınamadı: {e}")

    def _run_websocket(self, symbol):
        stream_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{self.interval}"
        while not self._stop_event.is_set():
            try:
                ws = websocket.WebSocketApp(
                    stream_url,
                    on_open=lambda ws: logging.info(f"✅ Bağlantı açıldı: {symbol} ({self.name})"),
                    on_message=lambda ws, msg: self._on_message(ws, msg, symbol),
                    on_error=lambda ws, err: logging.error(f"❌ Hata ({self.name}): {symbol} - {err}"),
                    on_close=lambda ws, code, msg: logging.warning(
                        f"🔌 Bağlantı kapandı: {symbol} ({self.name}). Yeniden bağlanılıyor...")
                )
                ws.run_forever(ping_interval=60, ping_timeout=10)
            except Exception as e:
                logging.critical(f"KRİTİK WebSocket Hatası ({symbol}, {self.name}): {e}")
            if not self._stop_event.is_set():
                time.sleep(10)


    def _reset_position_state(self, symbol):
        # Hafızadaki durumu sıfırla
        if symbol in self.portfolio_data:
            self.portfolio_data[symbol]['position'] = None
            self.portfolio_data[symbol]['entry_price'] = 0
            self.portfolio_data[symbol]['stop_loss_price'] = 0
            self.portfolio_data[symbol]['tp1_price'] = 0
            self.portfolio_data[symbol]['tp2_price'] = 0
            self.portfolio_data[symbol]['tp1_hit'] = False
            self.portfolio_data[symbol]['tp2_hit'] = False

        # Veritabanındaki pozisyonu temizle
        update_position(self.id, symbol, None, 0, 0, 0, 0, False, False)

    def _on_message(self, ws, message, symbol):
        """WebSocket'ten gelen mesajları işler."""
        try:
            json_message = json.loads(message)
            if 'k' in json_message:
                kline = json_message['k']
                symbol = kline['s']
                is_closed = kline['x']

                # Sadece ilgili stratejinin sembollerini dinle
                if symbol not in self.symbols:
                    return

                high_price = float(kline['h'])
                low_price = float(kline['l'])
                close_price = float(kline['c'])

                # Log için son fiyatı kaydet
                self.last_prices[symbol] = close_price

                # --- Mevcut açık pozisyonlar için SL/TP kontrolü ---

                symbol_data = self.portfolio_data.get(symbol)

                if symbol_data and symbol_data.get('position'):
                    pos_type = symbol_data.get('position')
                    sl_price = symbol_data.get('stop_loss_price')
                    tp1_price = symbol_data.get('tp1_price')
                    tp2_price = symbol_data.get('tp2_price')

                    # LONG Pozisyon için kontrol
                    if pos_type == 'Long':
                        # Stop-Loss kontrolü (Değişiklik yok)
                        if sl_price and low_price <= sl_price:
                            self._close_position(symbol, sl_price, "Stop-Loss")
                            return

                        # Take-Profit 1 kontrolü (Değişiklik yok)
                        if tp1_price and not symbol_data.get('tp1_hit', False) and high_price >= tp1_price:
                            tp1_size_pct = self.params.get('tp1_size_pct', 50)
                            self._close_position(symbol, tp1_price, "Take-Profit 1", size_pct_to_close=tp1_size_pct)

                        # Take-Profit 2 kontrolü 'elif' ile daha güvenli hale getirildi
                        elif tp2_price and symbol_data.get('tp1_hit', False) and not symbol_data.get('tp2_hit',
                                                                                                     False) and high_price >= tp2_price:
                            self._close_position(symbol, tp2_price, "Take-Profit 2", size_pct_to_close=100)

                        # SHORT Pozisyon için kontrol (Aynı mantık)
                    elif pos_type == 'Short':
                        # Stop-Loss kontrolü (Değişiklik yok)
                        if sl_price and high_price >= sl_price:
                            self._close_position(symbol, sl_price, "Stop-Loss")
                            return

                        # Take-Profit 1 kontrolü (Değişiklik yok)
                        if tp1_price and not symbol_data.get('tp1_hit', False) and low_price <= tp1_price:
                            tp1_size_pct = self.params.get('tp1_size_pct', 50)
                            self._close_position(symbol, tp1_price, "Take-Profit 1", size_pct_to_close=tp1_size_pct)

                        # Take-Profit 2 kontrolü 'elif' ile daha güvenli hale getirildi
                        elif tp2_price and symbol_data.get('tp1_hit', False) and not symbol_data.get('tp2_hit',
                                                                                                     False) and low_price <= tp2_price:
                            self._close_position(symbol, tp2_price, "Take-Profit 2", size_pct_to_close=100)

            # Mum kapanışındaki sinyal mantığı (değişiklik yok)
            is_kline_closed = kline.get('x', False)
            if not is_kline_closed:
                return

            # ... (fonksiyonun geri kalanı aynı)
            df = self.portfolio_data[symbol]['df']
            kline_timestamp = pd.to_datetime(kline['t'], unit='ms')

            if not df.empty and kline_timestamp <= df.index[-1]:
                df.iloc[-1] = [float(kline['o']), float(kline['h']), float(kline['l']), float(kline['c']),
                               float(kline['v'])]
            else:
                new_kline_df = pd.DataFrame(
                    [{'Open': float(kline['o']), 'High': float(kline['h']), 'Low': float(kline['l']),
                      'Close': float(kline['c']), 'Volume': float(kline['v'])}],
                    index=[kline_timestamp]
                )
                df = pd.concat([df, new_kline_df])

            if len(df) > 201:
                df = df.iloc[1:]

            self.portfolio_data[symbol]['df'] = df

            # --- YENİ: Sinyal Üretme Mantığı ---
            raw_signal = 'Bekle'  # Varsayılan sinyal
            price = df.iloc[-1]['Close']

            # EĞER RL MODELİ ATANMIŞSA, KARARI AJANA BIRAK
            if self.rl_model:
                try:
                    # 1. Gözlem verisini hazırla (trading_env.py'deki mantıkla aynı)
                    temp_env = TradingEnv(df)  # Veriyi hazırlamak için geçici bir env oluştur
                    obs_df = temp_env.df

                    # Son adıma ait gözlemi al
                    last_obs_series = obs_df.iloc[-1]

                    # Ortamdaki ek bilgileri ekle (bakiye, pozisyon, giriş fiyatı)
                    # Canlı işlemde bakiye takibi karmaşık olacağından, şimdilik temsili değerler kullanıyoruz.
                    # Asıl önemli olan piyasa verisidir.
                    current_position_state = 1 if self.portfolio_data.get(symbol, {}).get('position') == 'Long' else 0
                    entry_price = self.portfolio_data.get(symbol, {}).get('entry_price', 0)
                    pnl = 0 if entry_price == 0 else (price - entry_price) / entry_price

                    additional_info = np.array([10000, current_position_state, entry_price, pnl], dtype=np.float32)

                    # Gözlemi oluştur
                    obs = np.concatenate((last_obs_series.values.astype(np.float32), additional_info))

                    # 2. Modelden tahmin al
                    action, _ = self.rl_model.predict(obs, deterministic=True)

                    # 3. Aksiyonu sinyale çevir
                    if action == 1:
                        raw_signal = 'Al'
                    elif action == 2:
                        raw_signal = 'Short'  # RL ortamında SAT = Short pozisyon açmak
                    else:
                        raw_signal = 'Bekle'

                    logging.info(f"🤖 RL AJAN KARARI ({self.name}/{symbol}): Aksiyon={action} -> Sinyal='{raw_signal}'")

                except Exception as e:
                    logging.error(f"❌ RL AJAN HATA ({self.name}/{symbol}): Sinyal üretilemedi: {e}")
                    raw_signal = 'Bekle'  # Hata durumunda bekle

            # EĞER RL MODELİ YOKSA, STANDART İNDİKATÖR MANTIĞINI KULLAN
            else:

                # 1. Göstergeleri hesapla
                df_indicators = generate_all_indicators(df, **self.params)

                # 2. Ham sinyalleri üret
                df_signals = generate_signals(df_indicators, **self.params)

                # ================== DÜZELTME BAŞLANGICI ==================
                # 3. MTA (Çoklu Zaman Dilimi) Filtresini Uygula
                if self.params.get('use_mta', False):
                    higher_tf = self.params.get('higher_timeframe', '4h')
                    trend_ema = self.params.get('trend_ema_period', 50)

                    # Üst zaman dilimi verisini çek
                    df_higher = get_binance_klines(symbol, higher_tf, limit=1000)

                    if df_higher is not None and not df_higher.empty:
                        # Trendi hesapla ve alt zaman dilimine ekle
                        df_with_trend = add_higher_timeframe_trend(df_signals, df_higher, trend_ema)
                        # Sinyalleri filtrele
                        df_filtered = filter_signals_with_trend(df_with_trend)
                        final_df = df_filtered
                    else:
                        logging.warning(
                            f"UYARI ({self.name}): {symbol} için üst zaman dilimi ({higher_tf}) verisi alınamadı. MTA filtresi atlanıyor.")
                        final_df = df_signals
                else:
                    final_df = df_signals
                # ================== DÜZELTME SONU ==================

                # Ana veri çerçevesini güncel göstergelerle değiştir
                self.portfolio_data[symbol]['df'] = final_df

                last_row = final_df.iloc[-1]
                raw_signal = last_row['Signal']
                price = last_row['Close']

                current_position = self.portfolio_data.get(symbol, {}).get('position')
                last_signal = self.portfolio_data.get(symbol, {}).get('last_signal')

                # --- YENİ KONTROL ---
                # Eğer pozisyon yoksa ve gelen sinyal bir öncekiyle aynı ise (ve "Bekle" değilse) işlemi tekrar yapma.
                if current_position is None and raw_signal == last_signal and raw_signal != 'Bekle':
                    return  # Fonksiyondan çıkarak mükerrer işlemi engelle

                if (current_position == 'Long' and raw_signal == 'Short') or \
                        (current_position == 'Short' and raw_signal == 'Al'):
                    self._close_position(symbol, price, "Karşıt Sinyal", size_pct_to_close=100.0)
                    self.portfolio_data[symbol]['last_signal'] = raw_signal  # Pozisyon kapanınca son sinyali güncelle

                elif current_position is None:
                    if self.position_locks[symbol].acquire(blocking=False):
                        try:
                            if self.portfolio_data.get(symbol, {}).get('position') is None:
                                self.config = next((s for s in get_all_strategies() if s['id'] == self.id), self.config)
                                if self.config.get('status') == 'running' and self.config.get(
                                        'orchestrator_status') == 'active':
                                    new_pos = None
                                    if raw_signal == 'Al' and self.params.get('signal_direction', 'Both') != 'Short':
                                        new_pos = 'Long'
                                    elif raw_signal == 'Short' and self.params.get('signal_direction',
                                                                                   'Both') != 'Long':
                                        new_pos = 'Short'
                                    if new_pos:
                                        self._open_new_position(symbol, new_pos, price, final_df)
                                        # --- YENİ GÜNCELLEME ---
                                        # Pozisyon açıldıktan sonra son sinyali kaydet
                                        self.portfolio_data[symbol]['last_signal'] = raw_signal
                        finally:
                            self.position_locks[symbol].release()

        except Exception as e:
            logging.error(f"KRİTİK HATA ({symbol}, {self.name}): Mesaj işlenirken sorun: {e}")
            logging.error(traceback.format_exc())

    # multi_worker.py içine yerleştirilecek YENİ ve GÜVENLİ _open_new_position fonksiyonu

    def _open_new_position(self, symbol, new_pos, entry_price, df_with_indicators):
        # Veritabanından en güncel strateji yapılandırmasını al
        current_strategy_config = next((s for s in get_all_strategies() if s['id'] == self.id), self.config)
        params_from_db = current_strategy_config.get('strategy_params', {})

        # Eğer parametreler yanlışlıkla metin (string) olarak gelirse, onu JSON'a çevir.
        if isinstance(params_from_db, str):
            try:
                self.params = json.loads(params_from_db)
                logging.warning(f"UYARI ({self.name}): Strateji parametreleri metin olarak geldi ve JSON'a çevrildi.")
            except json.JSONDecodeError:
                logging.error(f"HATA ({self.name}): Strateji parametreleri çözümlenemedi. Boş olarak kabul ediliyor.")
                self.params = {}  # Hata durumunda boş bir sözlükle devam et
        else:
            # Eğer zaten doğru formattaysa (sözlük), doğrudan kullan.
            self.params = params_from_db
        # --- BİTİŞ: PARAMETRE GÜVENLİK KONTROLÜ ---

        # Risk seviyelerini (SL/TP) GÜVENLİ parametrelerle hesapla
        sl, tp1, tp2 = self._calculate_risk_levels(df_with_indicators, symbol, new_pos, entry_price)

        # Önce hafızadaki durumu güncelle
        self.portfolio_data[symbol].update({
            'position': new_pos, 'entry_price': entry_price,
            'stop_loss_price': sl, 'tp1_price': tp1, 'tp2_price': tp2,
            'tp1_hit': False, 'tp2_hit': False
        })

        # Veritabanına doğru hesaplanmış SL/TP değerlerini kaydet
        update_position(self.id, symbol, new_pos, entry_price, sl, tp1, tp2, False, False)
        self.notify_new_position(symbol, new_pos, entry_price, sl, tp1, tp2)

        is_trading_enabled = current_strategy_config.get('is_trading_enabled', False)
        if is_trading_enabled:
            leverage = self.params.get('leverage', 5)
            trade_amount_usdt = self.params.get('trade_amount_usdt', 10.0)
            margin_type = self.params.get('margin_type', 'ISOLATED')
            if entry_price <= 0:
                logging.error(f"HATA ({self.name}): Geçersiz giriş fiyatı ({entry_price}). İşlem atlanıyor.")
                return
            symbol_info = get_symbol_info(symbol)
            if not symbol_info:
                logging.error(f"HATA ({self.name}): {symbol} için işlem kuralları alınamadı. İşlem atlanıyor.")
                return
            quantity_precision = int(symbol_info['quantityPrecision'])
            quantity = (trade_amount_usdt * leverage) / entry_price
            quantity_to_trade = round(quantity, quantity_precision)
            if quantity_to_trade <= 0:
                logging.warning(
                    f"UYARI ({self.name}): Hesaplanan işlem miktarı ({quantity_to_trade}) sıfırdan küçük. İşlem atlanıyor.")
                return
            leverage_set = set_futures_leverage_and_margin(symbol, leverage, margin_type=margin_type)
            if not leverage_set:
                logging.error(f"HATA ({self.name}): Kaldıraç veya marjin tipi ayarlanamadığı için pozisyon açılmıyor.")
                return
            order_side = 'BUY' if new_pos == 'Long' else 'SELL'
            sl, tp1, tp2 = self._calculate_risk_levels(df_with_indicators, symbol, new_pos, entry_price)

            order_result = place_futures_order(symbol, order_side, quantity_to_trade)
            if order_result:
                logging.info(
                    f"BİLGİ ({self.name}): Ana {new_pos} pozisyonu başarıyla açıldı. Şartlı emirler gönderiliyor...")

                # --- YENİ EKLENECEK KISIM: TP ve SL emirlerini gönder ---
                tp_side = 'SELL' if new_pos == 'Long' else 'BUY'
                sl_side = 'SELL' if new_pos == 'Long' else 'BUY'

                # SL emrini tüm pozisyon için gönder
                if sl > 0:
                    place_futures_stop_market_order(symbol, sl_side, quantity_to_trade, sl)

                # TP1 ve TP2 emirlerini parsiyel olarak gönder
                if tp1 > 0:
                    tp1_size = self.params.get('tp1_size_pct', 50) / 100.0
                    tp1_quantity = round(quantity_to_trade * tp1_size, quantity_precision)
                    if tp1_quantity > 0:
                        place_futures_take_profit_order(symbol, tp_side, tp1_quantity, tp1)

                if tp2 > 0:
                    tp2_size = self.params.get('tp2_size_pct', 50) / 100.0
                    tp2_quantity = round(quantity_to_trade * tp2_size, quantity_precision)
                    if tp2_quantity > 0:
                        place_futures_take_profit_order(symbol, tp_side, tp2_quantity, tp2)

            else:
                logging.error(
                    f"HATA ({self.name}): {symbol} için {order_side} emri Binance'e gönderilemedi. Pozisyon veritabanında 'paper trade' olarak kalacak.")

        else:
            logging.info(
                f"BİLGİ ({self.name}): {symbol} için sinyal kaydedildi ve bildirildi ancak canlı işlem (trading) PASİF.")

    def _calculate_risk_levels(self, df_with_indicators, symbol, position_type, entry_price):
        params = self.params
        stop_loss_price, tp1_price, tp2_price = 0, 0, 0
        current_atr = df_with_indicators.iloc[-1].get('ATR', 0)


        if position_type == 'Long':
            # === DEĞİŞİKLİK BAŞLANGICI: Yüzde SL kontrolü eklendi ===
            if params.get('stop_loss_pct', 0) > 0:
                stop_loss_price = entry_price * (1 - params['stop_loss_pct'] / 100)
            elif params.get('atr_multiplier', 0) > 0 and current_atr > 0:
                stop_loss_price = entry_price - (current_atr * params['atr_multiplier'])
            # === DEĞİŞİKLİK SONU ===

            if params.get('tp1_pct', 0) > 0:
                tp1_price = entry_price * (1 + params['tp1_pct'] / 100)
            if params.get('tp2_pct', 0) > 0:
                tp2_price = entry_price * (1 + params['tp2_pct'] / 100)
        else: # Short Pozisyon
            # === DEĞİŞİKLİK BAŞLANGICI: Yüzde SL kontrolü eklendi ===
            if params.get('stop_loss_pct', 0) > 0:
                stop_loss_price = entry_price * (1 + params['stop_loss_pct'] / 100)
            elif params.get('atr_multiplier', 0) > 0 and current_atr > 0:
                stop_loss_price = entry_price + (current_atr * params['atr_multiplier'])
            # === DEĞİŞİKLİK SONU ===

            if params.get('tp1_pct', 0) > 0:
                tp1_price = entry_price * (1 - params['tp1_pct'] / 100)
            if params.get('tp2_pct', 0) > 0:
                tp2_price = entry_price * (1 - params['tp2_pct'] / 100)

        return stop_loss_price, tp1_price, tp2_price

    def notify_and_log(self, symbol, signal_type, price, pnl=None):
        if pnl is not None:
            # Kapanış nedenine göre emoji ve başlık belirle
            if "Take-Profit" in signal_type:
                emoji = "✅💰"
                status_text = f"Pozisyon Kârla Kapatıldı ({signal_type})"
            elif "Stop-Loss" in signal_type:
                emoji = "❌🛑"
                status_text = f"Pozisyon Stop-Loss Oldu"
            elif "Karşıt Sinyal" in signal_type:
                emoji = "🔄"
                status_text = "Pozisyon Karşıt Sinyal ile Kapatıldı"
            elif "Manuel" in signal_type:
                emoji = "🖐️"
                status_text = "Pozisyon Manuel Olarak Kapatıldı"
            else:  # Diğer durumlar için genel bir mesaj
                emoji = "✅" if pnl >= 0 else "❌"
                status_text = "Pozisyon Kapatıldı"

            pnl_text = f"\n📈 *P&L:* `{pnl:.2f}%`"
        else:  # Bu blok yeni pozisyon açılışları için kullanılır ve değişmez
            emoji, status_text, pnl_text = "🎯", signal_type, ""

        message = (f"{emoji} *{status_text}* \n\n"
                   f"🔹 *Strateji:* `{self.name}`\n"
                   f"📈 *Sembol:* `{symbol}`\n"
                   f"💰 *Kapanış Fiyatı:* `{price:.7f} USDT`{pnl_text}")

        logging.info(f"!!! {message} !!!")
        log_alarm_db(self.id, symbol, f"{status_text} ({self.name})", price)

        if self.params.get("telegram_enabled", False):
            token = self.params.get("telegram_token")
            chat_id = self.params.get("telegram_chat_id")
            if token and chat_id:
                send_telegram_message(message, token, chat_id)

    # --- TAMAMEN DÜZELTİLMİŞ BİLDİRİM FONKSİYONU ---
    def notify_new_position(self, symbol, signal_type, entry_price, stop_loss_price, tp1_price, tp2_price):
        """Sinyal ve pozisyon bildirimlerini SL/TP bilgisiyle oluşturur ve gönderir."""
        is_trading_enabled = self.config.get('is_trading_enabled', False)

        # tp1_text ve tp2_text değişkenlerini burada tanımlıyoruz
        stop_text = f"`{stop_loss_price:.6f}$`" if stop_loss_price > 0 else "`Yok`"
        tp1_text = f"`{tp1_price:.6f}$`" if tp1_price > 0 else "`Yok`"
        tp2_text = f"`{tp2_price:.6f}$`" if tp2_price > 0 else "`Yok`"

        signal_emoji = "🚀" if signal_type.upper() == "LONG" else "📉"

        if is_trading_enabled:
            title = f"*Yeni Pozisyon Açıldı: {symbol} - {signal_type.upper()}*"
            log_message = f"Yeni {signal_type.upper()} Pozisyon ({self.name})"
        else:
            title = f"*Sinyal Algılandı (Pasif Mod): {symbol} - {signal_type.upper()}*"
            log_message = f"Yeni {signal_type.upper()} Sinyali (Pasif) ({self.name})"

        # Mesaj oluşturma bloğu
        message = (f"{signal_emoji} {title}\n\n"
                   f"🔹 *Strateji:* `{self.name}`\n"
                   f"➡️ *Giriş Fiyatı:* `{entry_price:.4f}$`\n\n"
                   f"🛡️ *Zarar Durdur:* {stop_text}\n"
                   f"🎯 *Kar Al 1:* {tp1_text}\n"
                   f"🎯 *Kar Al 2:* {tp2_text}")

        logging.info("--- YENİ SİNYAL/POZİSYON ---\n" + message + "\n-----------------------------")
        log_alarm_db(self.id, symbol, log_message, entry_price)

        if self.params.get("telegram_enabled", False):
            token = self.params.get("telegram_token")
            chat_id = self.params.get("telegram_chat_id")
            if token and chat_id:
                send_telegram_message(message, token, chat_id)


def main_manager():
    logging.info("🚀 Çoklu Strateji Yöneticisi (Multi-Worker) Başlatıldı.")
    initialize_db()
    running_strategies = {}
    while True:
        try:
            strategies_in_db = get_all_strategies()
            db_strategy_map = {s['id']: s for s in strategies_in_db}
            db_ids = set(db_strategy_map.keys())
            running_ids = set(running_strategies.keys())
            for strategy_id in (db_ids - running_ids):
                strategy_config = db_strategy_map[strategy_id]
                logging.info(f"✅ YENİ STRATEJİ BULUNDU: '{strategy_config['name']}'. Başlatılıyor...")
                runner = StrategyRunner(strategy_config)
                running_strategies[runner.id] = runner
                runner.start()
            for strategy_id in (running_ids - db_ids):
                logging.warning(f"🛑 SİLİNMİŞ STRATEJİ: '{running_strategies[strategy_id].name}'. Durduruluyor...")
                running_strategies[strategy_id].stop()
                del running_strategies[strategy_id]
            for strategy_id in running_ids.intersection(db_ids):
                runner = running_strategies[strategy_id]
                db_config = db_strategy_map[strategy_id]
                if runner.config != db_config:
                    logging.info(f"🔄 GÜNCELLENMİŞ STRATEJİ: '{runner.name}'. Yeni ayarlarla yeniden başlatılıyor...")
                    runner.stop()
                    new_runner = StrategyRunner(db_config)
                    running_strategies[strategy_id] = new_runner
                    new_runner.start()
        except Exception as e:
            logging.error(f"HATA: Yönetici döngüsünde beklenmedik bir hata oluştu: {e}")
            logging.error(traceback.format_exc())
        time.sleep(5)


if __name__ == "__main__":
    if not create_lock_file():
        logging.error("❌ HATA: multi_worker.py zaten çalışıyor. Yeni bir kopya başlatılamadı.")
        sys.exit(1)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)
    try:
        main_manager()
    finally:
        remove_lock_file()
        logging.info("Temizlik yapıldı ve script sonlandı.")