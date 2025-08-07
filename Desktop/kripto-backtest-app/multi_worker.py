# multi_worker.py (Veritabanı Entegreli, Pozisyon Durumunu Kaydeden ve Detaylı Bildirim Gönderen Nihai Hali)

import json
import time
import threading
import pandas as pd
import websocket
from datetime import datetime


# Projenizdeki mevcut modülleri kullanıyoruz
from utils import get_binance_klines
from indicators import generate_all_indicators
from signals import generate_signals
from telegram_alert import send_telegram_message

# YENİ: Dosya importları yerine veritabanı fonksiyonlarını import ediyoruz
from database import (
    initialize_db,
    get_all_strategies,
    update_position,
    get_positions_for_strategy,
    log_alarm_db  # alarm_log.py yerine doğrudan DB fonksiyonunu kullanabiliriz
)


# --- Bir Stratejiyi ve Onun Sembollerini Yöneten Sınıf ---
class StrategyRunner:
    def __init__(self, strategy_config):
        self.config = strategy_config
        self.id = strategy_config['id']
        self.name = strategy_config['name']
        self.symbols = strategy_config['symbols']
        self.interval = strategy_config['interval']
        self.params = strategy_config['strategy_params']
        self.portfolio_data = {}  # Canlı DataFrame'leri ve geçici verileri tutar
        self.ws_threads = {}
        self._stop_event = threading.Event()
        self._load_positions()

    def _load_positions(self):
        """Stratejiye ait pozisyonları VERİTABANINDAN yükler."""
        try:
            # get_positions_for_strategy, sembole göre pozisyonları içeren bir dict döndürür
            # Örn: { "BTCUSDT": {"position": "Long", "entry_price": 12345}, ... }
            loaded_positions = get_positions_for_strategy(self.id)
            self.portfolio_data.update(loaded_positions)
            print(f"BİLGİ ({self.name}): Veritabanından mevcut pozisyonlar yüklendi.")
        except Exception as e:
            print(f"HATA ({self.name}): Veritabanından pozisyonlar okunurken hata: {e}")
            self.portfolio_data = {}

    def start(self):
        """Stratejiyi ve içindeki tüm semboller için WebSocket'leri başlatır."""
        print(f"✅ Strateji BAŞLATILIYOR: '{self.name}' (ID: {self.id})")
        for symbol in self.symbols:
            try:
                initial_df = get_binance_klines(symbol, self.interval, limit=200)
                if initial_df is None or initial_df.empty:
                    print(f"HATA ({self.name}): {symbol} için başlangıç verisi alınamadı. Bu sembol atlanıyor.")
                    continue

                # Eğer sembol için pozisyon bilgisi yüklenmemişse, varsayılan olarak başlat
                if symbol not in self.portfolio_data:
                    self.portfolio_data[symbol] = {'position': None, 'entry_price': 0}

                # Canlı DataFrame'i portfolio_data'ya ekle
                self.portfolio_data[symbol]['df'] = initial_df

                ws_thread = threading.Thread(target=self._run_websocket, args=(symbol,), daemon=True)
                self.ws_threads[symbol] = ws_thread
                ws_thread.start()
                time.sleep(0.5)  # API rate limitlerini aşmamak için kısa bir bekleme
            except Exception as e:
                print(f"KRİTİK HATA ({self.name}): {symbol} başlatılırken bir sorun oluştu: {e}")

    def stop(self):
        """Stratejiyi ve çalışan tüm WebSocket bağlantılarını durdurur."""
        print(f"🛑 Strateji DURDURULUYOR: '{self.name}' (ID: {self.id})")
        self._stop_event.set()

    def _run_websocket(self, symbol):
        """Tek bir sembol için WebSocket'i çalıştıran ve kesinti durumunda yeniden bağlanan fonksiyon."""
        stream_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{self.interval}"
        reconnect_delay = 5
        max_reconnect_delay = 60
        while not self._stop_event.is_set():
            try:
                ws = websocket.WebSocketApp(
                    stream_url,
                    on_open=lambda ws: print(f"✅ Bağlantı açıldı: {symbol} ({self.name})"),
                    on_message=lambda ws, msg: self._on_message(ws, msg, symbol),
                    on_error=lambda ws, err: print(f"❌ Hata ({self.name}): {symbol} - {err}"),
                    on_close=lambda ws, code, msg: print(
                        f"🔌 Bağlantı kapandı: {symbol} ({self.name}). Yeniden bağlanma denenecek...")
                )
                reconnect_delay = 5
                ws.run_forever(ping_interval=60, ping_timeout=10)
            except Exception as e:
                print(f"KRİTİK WebSocket Hatası ({symbol}, {self.name}): {e}")

            if not self._stop_event.is_set():
                print(f"-> {reconnect_delay} saniye sonra yeniden bağlanma denemesi yapılacak: {symbol}")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

    def _on_message(self, ws, message, symbol):
        """WebSocket mesajlarını işleyen ve pozisyon durumunu yöneten ana mantık."""
        try:
            data = json.loads(message)
            kline = data.get('k')
            if not kline or not kline.get('x'): return  # Sadece kapanmış mumlarla işlem yap

            print(f"-> Yeni mum: {symbol} ({self.name})")

            # Gelen yeni kline'ı DataFrame'e çevir ve ana DataFrame'e ekle/güncelle
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

            # Sinyal üretme ve pozisyon yönetimi
            df_indicators = generate_all_indicators(df, **self.params)
            df_signals = generate_signals(df_indicators, **self.params)
            last_row = df_signals.iloc[-1]
            raw_signal = last_row['Signal']
            price = last_row['Close']

            current_position = self.portfolio_data.get(symbol, {}).get('position')
            entry_price = self.portfolio_data.get(symbol, {}).get('entry_price', 0)

            # POZİSYON KAPATMA
            if (current_position == 'Long' and raw_signal == 'Sat') or \
                    (current_position == 'Short' and raw_signal == 'Al'):

                pnl = ((price - entry_price) / entry_price * 100) if current_position == 'Long' else (
                            (entry_price - price) / entry_price * 100)
                self.notify_and_log(symbol, f"{current_position.upper()} Pozisyonu KAPAT", price, pnl)

                # Durumu hem hafızada hem veritabanında güncelle
                self.portfolio_data[symbol]['position'] = None
                self.portfolio_data[symbol]['entry_price'] = 0
                update_position(self.id, symbol, None, 0)

            # YENİ POZİSYON AÇMA
            elif current_position is None:
                new_pos = None
                if raw_signal == 'Al' and self.params.get('signal_direction', 'Both') != 'Short':
                    new_pos = 'Long'
                elif raw_signal == 'Sat' and self.params.get('signal_direction', 'Both') != 'Long':
                    new_pos = 'Short'

                if new_pos:
                    self.notify_new_position(symbol, new_pos, price)
                    # Durumu hem hafızada hem veritabanında güncelle
                    self.portfolio_data[symbol]['position'] = new_pos
                    self.portfolio_data[symbol]['entry_price'] = price
                    update_position(self.id, symbol, new_pos, price)

        except Exception as e:
            print(f"KRİTİK HATA ({symbol}, {self.name}): Mesaj işlenirken sorun oluştu: {e}")

    def notify_and_log(self, symbol, signal_type, price, pnl=None):
        """Pozisyon kapatma gibi genel bildirimler için kullanılır."""
        # ... (Bu fonksiyonun içeriği aynı kalabilir) ...
        # Sadece log_alarm çağrısı artık veritabanına yazan versiyonu kullanacak
        emoji_map = {"LONG Pozisyonu": "✅", "SHORT Pozisyonu": "✅"}
        key_word = " ".join(signal_type.split()[:2])
        emoji = emoji_map.get(key_word, "🎯")
        pnl_text = f"\n📈 *P&L:* `{pnl:.2f}%`" if pnl is not None else ""
        message = (f"{emoji} *{signal_type}* \n\n"
                   f"🔹 *Strateji:* `{self.name}`\n"
                   f"📈 *Sembol:* `{symbol}`\n"
                   f"💰 *Fiyat:* `{price:.7f} USDT`"
                   f"{pnl_text}")
        print(f"!!! {message} !!!")

        # log_alarm artık log_alarm_db'ye yönleniyor
        log_alarm_db(symbol, f"{signal_type} ({self.name})", price)

        if self.params.get("telegram_enabled", False):
            token = self.params.get("telegram_token")
            chat_id = self.params.get("telegram_chat_id")
            if token and chat_id:
                send_telegram_message(message, token, chat_id)

    def notify_new_position(self, symbol, signal_type, entry_price):
        """Yeni bir pozisyon açıldığında detaylı bildirim gönderir."""
        # ... (Bu fonksiyonun içeriği de aynı kalabilir) ...
        params = self.params
        stop_loss_price = 0
        stop_loss_pct = 0
        if params.get('stop_loss_pct', 0) > 0:
            stop_loss_pct = params['stop_loss_pct']
            if signal_type == 'LONG':
                stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
            else:
                stop_loss_price = entry_price * (1 + stop_loss_pct / 100)
        tp_levels = []
        if signal_type == 'LONG':
            tp1_pct = params.get('take_profit_pct', 5.0)
            tp2_pct = tp1_pct * 1.618
            tp3_pct = tp1_pct * 2.618
            tp_levels.extend([
                {'price': entry_price * (1 + tp1_pct / 100), 'pct': tp1_pct},
                {'price': entry_price * (1 + tp2_pct / 100), 'pct': tp2_pct},
                {'price': entry_price * (1 + tp3_pct / 100), 'pct': tp3_pct}
            ])
        else:
            tp1_pct = params.get('take_profit_pct', 5.0)
            tp2_pct = tp1_pct * 1.618
            tp3_pct = tp1_pct * 2.618
            tp_levels.extend([
                {'price': entry_price * (1 - tp1_pct / 100), 'pct': tp1_pct},
                {'price': entry_price * (1 - tp2_pct / 100), 'pct': tp2_pct},
                {'price': entry_price * (1 - tp3_pct / 100), 'pct': tp3_pct}
            ])
        tp_text_lines = [f"{lvl['price']:.6f}$ +%{lvl['pct']:.1f}" for lvl in tp_levels]
        tp_text = "\n".join(tp_text_lines)
        stop_text = f"{stop_loss_price:.6f}$ -%{stop_loss_pct:.1f}%"
        signal_emoji = "🟢" if signal_type == "LONG" else "🔴"
        message = (
            f"{signal_emoji} *{symbol}: {signal_type}*\n\n"
            f"Giriş: `{entry_price:.4f}$`\n\n"
            f"**Kâr Al Seviyeleri:**\n"
            f"`{tp_text}`\n\n"
            f"**Stop:**\n`{stop_text}`\n\n"
            f"_TP1 sonrası stop girişe çekilmelidir._\n"
            f"_Finansal Tavsiye İçermez._"
        )
        print("--- YENİ POZİSYON SİNYALİ ---")
        print(message)
        print("-----------------------------")
        log_alarm_db(symbol, f"Yeni {signal_type} Pozisyon ({self.name})", entry_price)
        if self.params.get("telegram_enabled", False):
            token = self.params.get("telegram_token")
            chat_id = self.params.get("telegram_chat_id")
            if token and chat_id:
                send_telegram_message(message, token, chat_id)


# --- Ana Yönetici Döngüsü ---
def main_manager():
    print("🚀 Çoklu Strateji Yöneticisi (Multi-Worker) Başlatıldı.")
    # Uygulama başlangıcında veritabanını ve tabloları hazırla
    initialize_db()

    running_strategies = {}  # Hafızada çalışan StrategyRunner objelerini tutar
    while True:
        try:
            # Stratejileri dosyadan değil, veritabanından oku
            strategies_in_db = get_all_strategies()
            db_ids = {s['id'] for s in strategies_in_db}
            running_ids = set(running_strategies.keys())

            # YENİ EKLENEN STRATEJİLERİ BAŞLAT
            new_ids = db_ids - running_ids
            for strategy_config in strategies_in_db:
                if strategy_config['id'] in new_ids:
                    runner = StrategyRunner(strategy_config)
                    running_strategies[runner.id] = runner
                    runner.start()

            # SİLİNEN STRATEJİLERİ DURDUR
            removed_ids = running_ids - db_ids
            for strategy_id in removed_ids:
                if strategy_id in running_strategies:
                    print(f"Strateji '{running_strategies[strategy_id].name}' veritabanından silinmiş, durduruluyor.")
                    running_strategies[strategy_id].stop()
                    # Pozisyon dosyasını silmeye gerek yok, veritabanında kalabilirler.
                    del running_strategies[strategy_id]

        except Exception as e:
            print(f"Yönetici döngüsünde beklenmedik bir hata oluştu: {e}")

        time.sleep(5)


if __name__ == "__main__":
    main_manager()