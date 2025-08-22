# multi_worker.py (İşlem akışı düzeltilmiş ve en stabil hale getirilmiş nihai hali)

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
from trade_executor import set_futures_leverage_and_margin, place_futures_order, get_open_position_amount, \
    get_symbol_info

# --- Proje Modülleri ---
from utils import get_binance_klines
from indicators import generate_all_indicators
from signals import generate_signals
from telegram_alert import send_telegram_message
from database import (
    initialize_db, get_all_strategies, update_position,
    get_positions_for_strategy, log_alarm_db,
    get_and_clear_pending_actions
)

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
        self.params = strategy_config['strategy_params']
        self.portfolio_data = {}
        self.ws_threads = {}
        self._stop_event = threading.Event()
        self.position_locks = {symbol: threading.Lock() for symbol in self.symbols}
        self._load_positions()

    def _load_positions(self):
        try:
            loaded_positions = get_positions_for_strategy(self.id)
            self.portfolio_data.update(loaded_positions)
            logging.info(f"BİLGİ ({self.name}): Veritabanından mevcut pozisyonlar yüklendi.")
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
                        'tp1_price': 0, 'tp2_price': 0, 'tp1_hit': False, 'tp2_hit': False
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

    def _close_position(self, symbol: str, close_price: float, reason: str):
        symbol_data = self.portfolio_data.get(symbol, {})
        current_position = symbol_data.get('position')
        entry_price = symbol_data.get('entry_price', 0)
        if not current_position:
            return

        with self.position_locks[symbol]:
            is_trading_enabled = self.config.get('is_trading_enabled', False)
            if is_trading_enabled:
                quantity_to_close = get_open_position_amount(symbol)
                if quantity_to_close > 0:
                    close_side = 'SELL' if current_position == 'Long' else 'BUY'
                    place_futures_order(symbol, close_side, quantity_to_close)

            pnl = ((close_price - entry_price) / entry_price * 100) if current_position == 'Long' else (
                    (entry_price - close_price) / entry_price * 100)
            self.notify_and_log(symbol, f"Pozisyon '{reason}' ile Kapatıldı", close_price, pnl)

            self._reset_position_state(symbol)

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

    def _close_position_manually(self, symbol):
        if not self.portfolio_data.get(symbol, {}).get('position'):
            logging.info(f"BİLGİ ({self.name}): {symbol} için kapatılacak aktif pozisyon bulunamadı.")
            return
        try:
            latest_price = get_binance_klines(symbol, self.interval, limit=1).iloc[-1]['Close']
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
        self.portfolio_data[symbol]['position'] = None
        self.portfolio_data[symbol]['entry_price'] = 0
        self.portfolio_data[symbol]['stop_loss_price'] = 0
        self.portfolio_data[symbol]['tp1_price'] = 0
        self.portfolio_data[symbol]['tp2_price'] = 0
        self.portfolio_data[symbol]['tp1_hit'] = False
        self.portfolio_data[symbol]['tp2_hit'] = False
        update_position(self.id, symbol, None, 0)

    def _on_message(self, ws, message, symbol):
        try:
            data = json.loads(message)
            kline = data.get('k')
            if not kline: return

            high_price = float(kline['h'])
            low_price = float(kline['l'])
            symbol_data = self.portfolio_data.get(symbol, {})
            current_position = symbol_data.get('position')

            if current_position:
                sl_price = symbol_data.get('stop_loss_price', 0)
                if sl_price > 0:
                    if (current_position == 'Long' and low_price <= sl_price) or \
                            (current_position == 'Short' and high_price >= sl_price):
                        self._close_position(symbol, sl_price, "Stop-Loss")
                        return

            is_kline_closed = kline.get('x', False)
            if not is_kline_closed:
                return

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

            df_indicators = generate_all_indicators(df, **self.params)
            df_signals = generate_signals(df_indicators, **self.params)
            last_row = df_signals.iloc[-1]
            raw_signal = last_row['Signal']
            price = last_row['Close']

            current_position = self.portfolio_data.get(symbol, {}).get('position')

            if (current_position == 'Long' and raw_signal == 'Short') or \
                    (current_position == 'Short' and raw_signal == 'Al'):
                self._close_position(symbol, price, "Karşıt Sinyal")
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
                                elif raw_signal == 'Short' and self.params.get('signal_direction', 'Both') != 'Long':
                                    new_pos = 'Short'
                                if new_pos:
                                    self._open_new_position(symbol, new_pos, price)
                    finally:
                        self.position_locks[symbol].release()
        except Exception as e:
            logging.error(f"KRİTİK HATA ({symbol}, {self.name}): Mesaj işlenirken sorun: {e}")
            logging.error(traceback.format_exc())

    # --- YENİ VE EN STABİL İŞ AKIŞI ---
    def _open_new_position(self, symbol, new_pos, entry_price):
        """Sinyal geldiğinde pozisyon açma veya sinyal takibi yapma iş akışını yönetir."""
        current_strategy_config = next((s for s in get_all_strategies() if s['id'] == self.id), self.config)
        self.params = current_strategy_config.get('strategy_params', self.params)

        # 1. SL/TP seviyelerini hesapla
        sl, tp1, tp2 = self._calculate_risk_levels(symbol, new_pos, entry_price)

        # 2. Pozisyonu hafızaya ve veritabanına kaydet (Bu, sinyal çoklamasını engeller)
        self.portfolio_data[symbol]['position'] = new_pos
        self.portfolio_data[symbol]['entry_price'] = entry_price
        self.portfolio_data[symbol]['stop_loss_price'] = sl
        self.portfolio_data[symbol]['tp1_price'] = tp1
        self.portfolio_data[symbol]['tp2_price'] = tp2
        self.portfolio_data[symbol]['tp1_hit'] = False
        self.portfolio_data[symbol]['tp2_hit'] = False
        update_position(self.id, symbol, new_pos, entry_price)

        # 3. Tüm bilgilerle birlikte Telegram bildirimini gönder
        self.notify_new_position(symbol, new_pos, entry_price, sl)

        # 4. Canlı işlem aktif ise borsaya emir gönder
        is_trading_enabled = current_strategy_config.get('is_trading_enabled', False)
        if is_trading_enabled:
            leverage = self.params.get('leverage', 5)
            trade_amount_usdt = self.params.get('trade_amount_usdt', 10.0)

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

            leverage_set = set_futures_leverage_and_margin(symbol, leverage)
            if not leverage_set:
                logging.error(f"HATA ({self.name}): Kaldıraç ayarlanamadığı için pozisyon açılmıyor.")
                return

            order_side = 'BUY' if new_pos == 'Long' else 'SELL'
            order_result = place_futures_order(symbol, order_side, quantity_to_trade)

            if not order_result:
                logging.error(
                    f"HATA ({self.name}): {symbol} için {order_side} emri Binance'e gönderilemedi. Pozisyon veritabanında 'paper trade' olarak kalacak.")
        else:
            logging.info(
                f"BİLGİ ({self.name}): {symbol} için sinyal kaydedildi ve bildirildi ancak canlı işlem (trading) PASİF.")

    def _calculate_risk_levels(self, symbol, position_type, entry_price):
        params = self.params
        stop_loss_price, tp1_price, tp2_price = 0, 0, 0
        current_atr = self.portfolio_data[symbol]['df'].iloc[-1].get('ATR', 0)
        if position_type == 'Long':
            if params.get('atr_multiplier', 0) > 0 and current_atr > 0:
                stop_loss_price = entry_price - (current_atr * params['atr_multiplier'])
            if params.get('tp1_pct', 0) > 0:
                tp1_price = entry_price * (1 + params['tp1_pct'] / 100)
            if params.get('tp2_pct', 0) > 0:
                tp2_price = entry_price * (1 + params['tp2_pct'] / 100)
        else:
            if params.get('atr_multiplier', 0) > 0 and current_atr > 0:
                stop_loss_price = entry_price + (current_atr * params['atr_multiplier'])
            if params.get('tp1_pct', 0) > 0:
                tp1_price = entry_price * (1 - params['tp1_pct'] / 100)
            if params.get('tp2_pct', 0) > 0:
                tp2_price = entry_price * (1 - params['tp2_pct'] / 100)
        return stop_loss_price, tp1_price, tp2_price

    def notify_and_log(self, symbol, signal_type, price, pnl=None):
        if pnl is not None:
            emoji = "✅💰" if pnl >= 0 else "❌🛑"
            status_text = "Pozisyon Kârla Kapatıldı" if pnl >= 0 else "Pozisyon Zararla Kapatıldı"
            pnl_text = f"\n📈 *P&L:* `{pnl:.2f}%`"
        else:
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

    # --- YENİLENMİŞ BİLDİRİM FONKSİYONU ---
    def notify_new_position(self, symbol, signal_type, entry_price, stop_loss_price):
        """Sinyal ve pozisyon bildirimlerini SL/TP bilgisiyle oluşturur ve gönderir."""
        is_trading_enabled = self.config.get('is_trading_enabled', False)

        stop_text = f"`{stop_loss_price:.6f}$`" if stop_loss_price > 0 else "`Belirlenmedi`"
        signal_emoji = "🚀" if signal_type.upper() == "LONG" else "📉"

        if is_trading_enabled:
            title = f"*Yeni Pozisyon Açıldı: {symbol} - {signal_type.upper()}*"
            log_message = f"Yeni {signal_type.upper()} Pozisyon ({self.name})"
        else:
            title = f"*Sinyal Algılandı (Pasif Mod): {symbol} - {signal_type.upper()}*"
            log_message = f"Yeni {signal_type.upper()} Sinyali (Pasif) ({self.name})"

        message = (f"{signal_emoji} {title}\n\n"
                   f"🔹 *Strateji:* `{self.name}`\n"
                   f"➡️ *Giriş Fiyatı:* `{entry_price:.4f}$`\n\n"
                   f"🛡️ *Zarar Durdur:* {stop_text}\n")

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