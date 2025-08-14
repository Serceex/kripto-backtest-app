# multi_worker.py (Telegram bildirimine TP seviyeleri eklendi)

import json
import time
import threading
import pandas as pd
import websocket
import os
import sys
import signal
from datetime import datetime

# --- Proje Modülleri ---
from utils import get_binance_klines
from indicators import generate_all_indicators
from signals import generate_signals
from telegram_alert import send_telegram_message
from database import (
    initialize_db, get_all_strategies, update_position,
    get_positions_for_strategy, log_alarm_db
)

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
            print("✅ Kilit dosyası başarıyla kaldırıldı.")
        except OSError as e:
            print(f"⚠️ Kilit dosyası kaldırılamadı: {e}")


def graceful_shutdown(signum, frame):
    print(f"\n🛑 Kapanma sinyali ({signum}) alındı. Tüm işlemler durduruluyor...")
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
        self._load_positions()

    def _load_positions(self):
        try:
            loaded_positions = get_positions_for_strategy(self.id)
            self.portfolio_data.update(loaded_positions)
            print(f"BİLGİ ({self.name}): Veritabanından mevcut pozisyonlar yüklendi.")
        except Exception as e:
            print(f"HATA ({self.name}): Veritabanından pozisyonlar okunurken hata: {e}")
            self.portfolio_data = {}

    def start(self):
        print(f"✅ Strateji BAŞLATILIYOR: '{self.name}' (ID: {self.id})")
        for symbol in self.symbols:
            try:
                initial_df = get_binance_klines(symbol, self.interval, limit=200)
                if initial_df is None or initial_df.empty:
                    print(f"HATA ({self.name}): {symbol} için başlangıç verisi alınamadı. Atlanıyor.")
                    continue

                if symbol not in self.portfolio_data:
                    self.portfolio_data[symbol] = {'position': None, 'entry_price': 0}

                self.portfolio_data[symbol]['df'] = initial_df

                ws_thread = threading.Thread(target=self._run_websocket, args=(symbol,), daemon=True)
                self.ws_threads[symbol] = ws_thread
                ws_thread.start()
                time.sleep(0.5)
            except Exception as e:
                print(f"KRİTİK HATA ({self.name}): {symbol} başlatılırken sorun: {e}")

    def stop(self):
        print(f"🛑 Strateji DURDURULUYOR: '{self.name}' (ID: {self.id})")
        self._stop_event.set()

    def _run_websocket(self, symbol):
        stream_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{self.interval}"
        while not self._stop_event.is_set():
            try:
                ws = websocket.WebSocketApp(
                    stream_url,
                    on_open=lambda ws: print(f"✅ Bağlantı açıldı: {symbol} ({self.name})"),
                    on_message=lambda ws, msg: self._on_message(ws, msg, symbol),
                    on_error=lambda ws, err: print(f"❌ Hata ({self.name}): {symbol} - {err}"),
                    on_close=lambda ws, code, msg: print(
                        f"🔌 Bağlantı kapandı: {symbol} ({self.name}). Yeniden bağlanılıyor...")
                )
                ws.run_forever(ping_interval=60, ping_timeout=10)
            except Exception as e:
                print(f"KRİTİK WebSocket Hatası ({symbol}, {self.name}): {e}")

            if not self._stop_event.is_set():
                time.sleep(10)

    def _on_message(self, ws, message, symbol):
        try:
            data = json.loads(message)
            kline = data.get('k')
            if not kline or not kline.get('x'): return

            new_kline_df = pd.DataFrame([{'timestamp': pd.to_datetime(kline['t'], unit='ms'), 'Open': float(kline['o']),
                                          'High': float(kline['h']), 'Low': float(kline['l']),
                                          'Close': float(kline['c']), 'Volume': float(kline['v']),
                                          }]).set_index('timestamp')

            df = self.portfolio_data[symbol]['df']
            if new_kline_df.index[0] in df.index:
                df.loc[new_kline_df.index] = new_kline_df.values
            else:
                df = pd.concat([df, new_kline_df])

            if len(df) > 201: df = df.iloc[1:]
            self.portfolio_data[symbol]['df'] = df

            df_indicators = generate_all_indicators(df, **self.params)
            df_signals = generate_signals(df_indicators, **self.params)
            last_row = df_signals.iloc[-1]
            raw_signal = last_row['Signal']
            price = last_row['Close']

            current_position = self.portfolio_data.get(symbol, {}).get('position')
            entry_price = self.portfolio_data.get(symbol, {}).get('entry_price', 0)

            if (current_position == 'Long' and raw_signal == 'Short') or \
                    (current_position == 'Short' and raw_signal == 'Al'):
                pnl = ((price - entry_price) / entry_price * 100) if current_position == 'Long' else (
                        (entry_price - price) / entry_price * 100)
                self.notify_and_log(symbol, f"{current_position.upper()} Pozisyonu KAPAT", price, pnl)
                self.portfolio_data[symbol]['position'] = None
                self.portfolio_data[symbol]['entry_price'] = 0
                update_position(self.id, symbol, None, 0)

            elif current_position is None:
                new_pos = None
                if raw_signal == 'Al' and self.params.get('signal_direction', 'Both') != 'Short':
                    new_pos = 'Long'
                elif raw_signal == 'Short' and self.params.get('signal_direction', 'Both') != 'Long':
                    new_pos = 'Short'

                if new_pos:
                    self.notify_new_position(symbol, new_pos, price)
                    self.portfolio_data[symbol]['position'] = new_pos
                    self.portfolio_data[symbol]['entry_price'] = price
                    update_position(self.id, symbol, new_pos, price)

        except Exception as e:
            print(f"KRİTİK HATA ({symbol}, {self.name}): Mesaj işlenirken sorun: {e}")

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
                   f"💰 *Kapanış Fiyatı:* `{price:.7f} USDT`"
                   f"{pnl_text}")
        print(f"!!! {message} !!!")
        log_alarm_db(symbol, f"{status_text} ({self.name})", price, strategy_id=self.id)

        if self.params.get("telegram_enabled", False):
            token = self.params.get("telegram_token")
            chat_id = self.params.get("telegram_chat_id")
            if token and chat_id:
                send_telegram_message(message, token, chat_id)

    # --- YENİLENMİŞ FONKSİYON ---
    def notify_new_position(self, symbol, signal_type, entry_price):
        params = self.params

        # Stop-Loss Fiyatını Hesapla
        stop_loss_price = 0
        current_atr = self.portfolio_data[symbol]['df'].iloc[-1].get('ATR', 0)
        if params.get('atr_multiplier', 0) > 0 and current_atr > 0:
            stop_loss_price = entry_price - (
                        current_atr * params['atr_multiplier']) if signal_type.upper() == 'LONG' else entry_price + (
                        current_atr * params['atr_multiplier'])
        elif params.get('stop_loss_pct', 0) > 0:
            stop_loss_price = entry_price * (
                        1 - params['stop_loss_pct'] / 100) if signal_type.upper() == 'LONG' else entry_price * (
                        1 + params['stop_loss_pct'] / 100)

        # Take-Profit Seviyelerini Hesapla
        tp_levels = []
        tp1_pct = params.get('tp1_pct', 0)
        tp2_pct = params.get('tp2_pct', 0)

        if signal_type.upper() == 'LONG':
            if tp1_pct > 0: tp_levels.append(
                {'price': entry_price * (1 + tp1_pct / 100), 'pct': tp1_pct, 'label': 'TP1'})
            if tp2_pct > 0: tp_levels.append(
                {'price': entry_price * (1 + tp2_pct / 100), 'pct': tp2_pct, 'label': 'TP2'})
        else:  # SHORT
            if tp1_pct > 0: tp_levels.append(
                {'price': entry_price * (1 - tp1_pct / 100), 'pct': tp1_pct, 'label': 'TP1'})
            if tp2_pct > 0: tp_levels.append(
                {'price': entry_price * (1 - tp2_pct / 100), 'pct': tp2_pct, 'label': 'TP2'})

        # Mesajı Oluştur
        tp_text = "\n".join([f"`{lvl['label']}: {lvl['price']:.6f}$ (+{lvl['pct']:.1f}%)`" for lvl in
                             tp_levels]) if tp_levels else "`Belirlenmedi`"
        stop_text = f"`{stop_loss_price:.6f}$`" if stop_loss_price > 0 else "`Belirlenmedi`"
        signal_emoji = "🚀" if signal_type.upper() == "LONG" else "📉"

        message = (
            f"{signal_emoji} *Yeni Pozisyon: {symbol} - {signal_type.upper()}*\n\n"
            f"🔹 *Strateji:* `{self.name}`\n"
            f"➡️ *Giriş Fiyatı:* `{entry_price:.4f}$`\n\n"
            f"💰 *Kâr Al Seviyeleri:*\n{tp_text}\n\n"
            f"🛡️ *Zarar Durdur:*\n{stop_text}\n"
        )
        if params.get('move_sl_to_be', False):
            message += f"\n_📌 Not: TP1 sonrası stop girişe çekilecektir._"

        print("--- YENİ POZİSYON SİNYALİ ---\n" + message + "\n-----------------------------")

        log_alarm_db(symbol, f"Yeni {signal_type.upper()} Pozisyon ({self.name})", entry_price, strategy_id=self.id)

        if self.params.get("telegram_enabled", False):
            token = self.params.get("telegram_token")
            chat_id = self.params.get("telegram_chat_id")
            if token and chat_id:
                send_telegram_message(message, token, chat_id)


def main_manager():
    """
    Veritabanını sürekli olarak kontrol eden ana yönetici fonksiyonu.
    """
    print("🚀 Çoklu Strateji Yöneticisi (Multi-Worker) Başlatıldı.")
    initialize_db()
    running_strategies = {}

    while True:
        try:
            strategies_in_db = get_all_strategies()
            db_strategy_map = {s['id']: s for s in strategies_in_db}
            db_ids = set(db_strategy_map.keys())
            running_ids = set(running_strategies.keys())

            new_ids = db_ids - running_ids
            for strategy_id in new_ids:
                strategy_config = db_strategy_map[strategy_id]
                print(f"✅ YENİ STRATEJİ BULUNDU: '{strategy_config['name']}'. Başlatılıyor...")
                runner = StrategyRunner(strategy_config)
                running_strategies[runner.id] = runner
                runner.start()

            removed_ids = running_ids - db_ids
            for strategy_id in removed_ids:
                print(f"🛑 SİLİNMİŞ STRATEJİ: '{running_strategies[strategy_id].name}'. Durduruluyor...")
                running_strategies[strategy_id].stop()
                del running_strategies[strategy_id]

            for strategy_id in running_ids.intersection(db_ids):
                runner = running_strategies[strategy_id]
                db_config = db_strategy_map[strategy_id]
                if runner.config != db_config:
                    print(f"🔄 GÜNCELLENMİŞ STRATEJİ: '{runner.name}'. Yeni ayarlarla yeniden başlatılıyor...")
                    runner.stop()
                    new_runner = StrategyRunner(db_config)
                    running_strategies[strategy_id] = new_runner
                    new_runner.start()

        except Exception as e:
            print(f"HATA: Yönetici döngüsünde beklenmedik bir hata oluştu: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(5)


if __name__ == "__main__":
    if not create_lock_file():
        print("❌ HATA: multi_worker.py zaten çalışıyor. Yeni bir kopya başlatılamadı.")
        sys.exit(1)

    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    try:
        main_manager()
    finally:
        remove_lock_file()
        print("Temizlik yapıldı ve script sonlandı.")