# multi_worker.py (Pozisyon Takibi ve Giriş/Çıkış Sinyalleri ile Güncellenmiş Nihai Hali)

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
from alarm_log import log_alarm

STRATEGIES_FILE = "strategies.json"


# --- Bir Stratejiyi ve Onun Sembollerini Yöneten Sınıf ---
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

    def start(self):
        """Stratejiyi ve içindeki tüm semboller için WebSocket'leri başlatır."""
        print(f"✅ Strateji BAŞLATILIYOR: '{self.name}' (ID: {self.id})")
        for symbol in self.symbols:
            try:
                initial_df = get_binance_klines(symbol, self.interval, limit=200)
                if initial_df is None or initial_df.empty:
                    print(f"HATA ({self.name}): {symbol} için başlangıç verisi alınamadı. Bu sembol atlanıyor.")
                    continue

                # Her sembol için pozisyon durumunu ve giriş fiyatını saklayacak yapı
                self.portfolio_data[symbol] = {
                    'df': initial_df,
                    'position': None,  # Aktif pozisyonu tutar: 'Long', 'Short' veya None
                    'entry_price': 0  # Pozisyona giriş fiyatı
                }

                ws_thread = threading.Thread(target=self._run_websocket, args=(symbol,), daemon=True)
                self.ws_threads[symbol] = ws_thread
                ws_thread.start()
                time.sleep(0.5)
            except Exception as e:
                print(f"KRİTİK HATA ({self.name}): {symbol} başlatılırken bir sorun oluştu: {e}")

    def stop(self):
        """Stratejiyi ve çalışan tüm WebSocket bağlantılarını durdurur."""
        print(f"🛑 Strateji DURDURULUYOR: '{self.name}' (ID: {self.id})")
        self._stop_event.set()

    def _run_websocket(self, symbol):
        """
        Tek bir sembol için WebSocket'i çalıştıran ve kesinti durumunda
        üstel geri çekilme (exponential backoff) ile yeniden bağlanan fonksiyon.
        """
        stream_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{self.interval}"
        reconnect_delay = 5  # Başlangıçtaki bekleme süresi (saniye)
        max_reconnect_delay = 60  # Maksimum bekleme süresi (saniye)

        while not self._stop_event.is_set():
            try:
                ws = websocket.WebSocketApp(
                    stream_url,
                    on_open=lambda ws: print(f"✅ Bağlantı açıldı: {symbol} ({self.name})"),
                    on_message=lambda ws, msg: self._on_message(ws, msg, symbol),
                    on_error=lambda ws, err: print(f"❌ Hata ({self.name}): {symbol} - {err}"),
                    on_close=lambda ws, code, msg: print(f"🔌 Bağlantı kapandı: {symbol} ({self.name}). Yeniden bağlanma denenecek...")
                )
                # run_forever() başarılı bir şekilde başlarsa, yeniden bağlanma gecikmesini sıfırla
                # Bu, başarılı bir bağlantıdan sonraki olası bir kopmada bekleme süresinin en baştan başlamasını sağlar.
                reconnect_delay = 5
                ws.run_forever(ping_interval=60, ping_timeout=10)

            except Exception as e:
                print(f"CRITICAL WebSocket Hatası ({symbol}, {self.name}): {e}")

            if not self._stop_event.is_set():
                print(f"-> {reconnect_delay} saniye sonra yeniden bağlanma denemesi yapılacak: {symbol}")
                time.sleep(reconnect_delay)
                # Bir sonraki deneme için bekleme süresini artır (maksimum değeri geçmeyecek şekilde)
                reconnect_delay = min(reconnect_delay * 2, max_reconnect_delay)

    def _on_message(self, ws, message, symbol):
        """WebSocket mesajlarını işleyen ve pozisyon durumunu yöneten ana mantık."""
        try:
            data = json.loads(message)
            kline = data.get('k')
            if not kline or not kline.get('x'): return

            print(f"-> Yeni mum: {symbol} ({self.name})")

            # Veri çerçevesini güncelle
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

            # Göstergeleri ve ham sinyalleri hesapla
            df_indicators = generate_all_indicators(df, **self.params)
            df_signals = generate_signals(df_indicators, **self.params)

            last_row = df_signals.iloc[-1]
            raw_signal = last_row['Signal']
            price = last_row['Close']

            current_position = self.portfolio_data[symbol].get('position')
            entry_price = self.portfolio_data[symbol].get('entry_price', 0)

            # --- YENİ POZİSYON YÖNETİM MANTIĞI ---

            # 1. POZİSYON KAPATMA KONTROLÜ
            if current_position == 'Long' and raw_signal == 'Sat':
                pnl = ((price - entry_price) / entry_price) * 100
                self.notify_and_log(symbol, "LONG Pozisyonu KAPAT", price, pnl)
                self.portfolio_data[symbol]['position'] = None
                self.portfolio_data[symbol]['entry_price'] = 0

            elif current_position == 'Short' and raw_signal == 'Al':
                pnl = ((entry_price - price) / entry_price) * 100
                self.notify_and_log(symbol, "SHORT Pozisyonu KAPAT", price, pnl)
                self.portfolio_data[symbol]['position'] = None
                self.portfolio_data[symbol]['entry_price'] = 0

            # 2. YENİ POZİSYON AÇMA KONTROLÜ
            elif current_position is None:
                if raw_signal == 'Al' and self.params.get('signal_direction', 'Both') != 'Short':
                    self.notify_and_log(symbol, "Yeni LONG Pozisyon", price)
                    self.portfolio_data[symbol]['position'] = 'Long'
                    self.portfolio_data[symbol]['entry_price'] = price

                elif raw_signal == 'Sat' and self.params.get('signal_direction', 'Both') != 'Long':
                    self.notify_and_log(symbol, "Yeni SHORT Pozisyon", price)
                    self.portfolio_data[symbol]['position'] = 'Short'
                    self.portfolio_data[symbol]['entry_price'] = price

        except Exception as e:
            print(f"KRİTİK HATA ({symbol}, {self.name}): Mesaj işlenirken sorun oluştu: {e}")

    def notify_and_log(self, symbol, signal_type, price, pnl=None):
        """Bildirim gönderme ve loglama işlemini merkezileştiren fonksiyon."""
        emoji_map = {
            "Yeni LONG": "🟢", "Yeni SHORT": "🔴",
            "LONG Kapat": "✅", "SHORT Kapat": "✅"
        }
        # Sinyal tipinden anahtar kelimeyi çıkar (ör: "Yeni LONG Pozisyon" -> "Yeni LONG")
        key_word = " ".join(signal_type.split()[:2])
        emoji = emoji_map.get(key_word, "🎯")

        pnl_text = f"\n📈 *P&L:* `{pnl:.2f}%`" if pnl is not None else ""

        message = (
            f"{emoji} *{signal_type}* \n\n"
            f"🔹 *Strateji:* `{self.name}`\n"
            f"📈 *Sembol:* `{symbol}`\n"
            f"💰 *Fiyat:* `{price:.7f} USDT`"
            f"{pnl_text}"
        )

        print(f"!!! {message} !!!")

        # Loglama için strateji adını sinyale ekle
        log_signal = f"{signal_type} ({self.name})"
        log_alarm(symbol, log_signal, price)

        if self.params.get("telegram_enabled", False):
            token = self.params.get("telegram_token")
            chat_id = self.params.get("telegram_chat_id")
            if token and chat_id:
                send_telegram_message(message, token, chat_id)


# --- Ana Yönetici Döngüsü (Değişiklik yok) ---
def main_manager():
    print("🚀 Çoklu Strateji Yöneticisi (Multi-Worker) Başlatıldı.")
    running_strategies = {}
    while True:
        try:
            with open(STRATEGIES_FILE, 'r') as f:
                strategies_on_disk = json.load(f)
            disk_ids = {s['id'] for s in strategies_on_disk}
            running_ids = set(running_strategies.keys())
            new_ids = disk_ids - running_ids
            for strategy_config in strategies_on_disk:
                if strategy_config['id'] in new_ids:
                    runner = StrategyRunner(strategy_config)
                    running_strategies[runner.id] = runner
                    runner.start()
            removed_ids = running_ids - disk_ids
            for strategy_id in removed_ids:
                if strategy_id in running_strategies:
                    print(f"Strateji '{running_strategies[strategy_id].name}' dosyadan silinmiş, durduruluyor.")
                    running_strategies[strategy_id].stop()
                    del running_strategies[strategy_id]
        except Exception as e:
            print(f"Yönetici döngüsünde beklenmedik bir hata oluştu: {e}")
        time.sleep(5)


if __name__ == "__main__":
    main_manager()