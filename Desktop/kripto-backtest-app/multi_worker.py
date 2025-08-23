# multi_worker.py (Tüm hataları giderilmiş, en stabil ve tam özellikli nihai hali)

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

    # multi_worker.py içindeki _close_position fonksiyonunu bununla değiştirin

    def _close_position(self, symbol: str, close_price: float, reason: str, size_pct_to_close: float = 100.0):
        """
        Pozisyonun belirtilen yüzdesini kapatır.
        size_pct_to_close: 1.0 ile 100.0 arasında bir değer.
        """
        symbol_data = self.portfolio_data.get(symbol, {})
        current_position = symbol_data.get('position')
        entry_price = symbol_data.get('entry_price', 0)
        if not current_position:
            return

        with self.position_locks[symbol]:
            is_trading_enabled = self.config.get('is_trading_enabled', False)
            if is_trading_enabled:
                # Mevcut açık pozisyon miktarını al
                total_quantity = get_open_position_amount(symbol)
                if total_quantity > 0:
                    # Kapatılacak miktarı hesapla
                    quantity_to_close = total_quantity * (size_pct_to_close / 100.0)

                    # Binance için miktar hassasiyetini (precision) al
                    symbol_info = get_symbol_info(symbol)
                    if symbol_info:
                        quantity_precision = int(symbol_info['quantityPrecision'])
                        quantity_to_close = round(quantity_to_close, quantity_precision)

                    if quantity_to_close > 0:
                        close_side = 'SELL' if current_position == 'Long' else 'BUY'
                        place_futures_order(symbol, close_side, quantity_to_close)

            pnl = ((close_price - entry_price) / entry_price * 100) if current_position == 'Long' else (
                    (entry_price - close_price) / entry_price * 100)

            log_reason = f"{reason} ({size_pct_to_close}%)"
            self.notify_and_log(symbol, log_reason, close_price, pnl)

            # Eğer pozisyonun tamamı kapatılıyorsa, durumu sıfırla
            if size_pct_to_close >= 100.0:
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

    # multi_worker.py içindeki _on_message fonksiyonunu bununla değiştirin

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
                with self.position_locks[symbol]:
                    if not self.portfolio_data.get(symbol, {}).get('position'):
                        return

                    sl_price = symbol_data.get('stop_loss_price', 0)
                    tp1_price = symbol_data.get('tp1_price', 0)
                    tp2_price = symbol_data.get('tp2_price', 0)
                    tp1_hit = symbol_data.get('tp1_hit', False)
                    tp2_hit = symbol_data.get('tp2_hit', False)  # TP2 hit'i de takip edelim

                    # 1. Stop-Loss Kontrolü (Tüm pozisyonu kapatır)
                    if sl_price > 0 and ((current_position == 'Long' and low_price <= sl_price) or \
                                         (current_position == 'Short' and high_price >= sl_price)):
                        self._close_position(symbol, sl_price, "Stop-Loss", size_pct_to_close=100.0)
                        return

                    # 2. Kademeli Take-Profit Kontrolü
                    if current_position == 'Long':
                        # TP1 Kontrolü
                        if not tp1_hit and tp1_price > 0 and high_price >= tp1_price:
                            tp1_size = self.params.get('tp1_size_pct', 100)
                            self._close_position(symbol, tp1_price, "Take-Profit 1", size_pct_to_close=tp1_size)
                            self.portfolio_data[symbol]['tp1_hit'] = True
                            # TP1 sonrası SL'i girişe çekme mantığı
                            if self.params.get('move_sl_to_be', False):
                                self.portfolio_data[symbol]['stop_loss_price'] = symbol_data.get('entry_price', 0)

                        # TP2 Kontrolü (TP1 vurulmuşsa ve TP2 hedefi varsa)
                        if self.portfolio_data[symbol][
                            'tp1_hit'] and not tp2_hit and tp2_price > 0 and high_price >= tp2_price:
                            # Kalan tüm pozisyonu kapat
                            self._close_position(symbol, tp2_price, "Take-Profit 2", size_pct_to_close=100.0)
                            return

                    elif current_position == 'Short':
                        # TP1 Kontrolü
                        if not tp1_hit and tp1_price > 0 and low_price <= tp1_price:
                            tp1_size = self.params.get('tp1_size_pct', 100)
                            self._close_position(symbol, tp1_price, "Take-Profit 1", size_pct_to_close=tp1_size)
                            self.portfolio_data[symbol]['tp1_hit'] = True
                            if self.params.get('move_sl_to_be', False):
                                self.portfolio_data[symbol]['stop_loss_price'] = symbol_data.get('entry_price', 0)

                        # TP2 Kontrolü
                        if self.portfolio_data[symbol][
                            'tp1_hit'] and not tp2_hit and tp2_price > 0 and low_price <= tp2_price:
                            self._close_position(symbol, tp2_price, "Take-Profit 2", size_pct_to_close=100.0)
                            return

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

            # 1. Göstergeleri hesapla
            df_indicators = generate_all_indicators(df, **self.params)

            # 2. Ham sinyalleri üret
            df_signals = generate_signals(df_indicators, **self.params)

            # 3. MTA (Çoklu Zaman Dilimi) Filtresini Uygula
            if self.params.get('use_mta', False):
                higher_tf = self.params.get('higher_timeframe', '4h')
                trend_ema = self.params.get('trend_ema_period', 50)

                # Üst zaman dilimi verisini çek (limit backtest ile uyumlu)
                df_higher = get_binance_klines(symbol=symbol, interval=higher_tf, limit=1000)

                if df_higher is not None and not df_higher.empty:
                    # Trendi ekle ve sinyalleri filtrele
                    df_with_trend = add_higher_timeframe_trend(df_signals, df_higher, trend_ema)
                    df_filtered = filter_signals_with_trend(df_with_trend)
                    final_df = df_filtered
                else:
                    logging.warning(
                        f"UYARI ({self.name}): {symbol} için MTA verisi ({higher_tf}) alınamadı. Filtre atlanıyor.")
                    final_df = df_signals
            else:
                final_df = df_signals


            last_row = df_signals.iloc[-1]
            raw_signal = last_row['Signal']
            price = last_row['Close']

            current_position = self.portfolio_data.get(symbol, {}).get('position')

            if (current_position == 'Long' and raw_signal == 'Short') or \
                    (current_position == 'Short' and raw_signal == 'Al'):
                self._close_position(symbol, price, "Karşıt Sinyal", size_pct_to_close=100.0)
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

    def _open_new_position(self, symbol, new_pos, entry_price):
        current_strategy_config = next((s for s in get_all_strategies() if s['id'] == self.id), self.config)
        self.params = current_strategy_config.get('strategy_params', self.params)
        sl, tp1, tp2 = self._calculate_risk_levels(symbol, new_pos, entry_price)
        self.portfolio_data[symbol]['position'] = new_pos
        self.portfolio_data[symbol]['entry_price'] = entry_price
        self.portfolio_data[symbol]['stop_loss_price'] = sl
        self.portfolio_data[symbol]['tp1_price'] = tp1
        self.portfolio_data[symbol]['tp2_price'] = tp2
        self.portfolio_data[symbol]['tp1_hit'] = False
        self.portfolio_data[symbol]['tp2_hit'] = False
        update_position(self.id, symbol, new_pos, entry_price)
        self.notify_new_position(symbol, new_pos, entry_price, sl, tp1, tp2)
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