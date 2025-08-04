# multi_worker.py

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
            # 1. Başlangıç verisini çek
            initial_df = get_binance_klines(symbol, self.interval, limit=200)
            if initial_df is None or initial_df.empty:
                print(f"HATA: {symbol} için başlangıç verisi alınamadı. Bu sembol atlanıyor.")
                continue

            self.portfolio_data[symbol] = {
                'df': initial_df,
                'last_signal': None,
            }

            # 2. Her sembol için WebSocket thread'ini başlat
            ws_thread = threading.Thread(target=self._run_websocket, args=(symbol,), daemon=True)
            self.ws_threads[symbol] = ws_thread
            ws_thread.start()
            time.sleep(0.5)  # Binance rate limit'e takılmamak için kısa bekleme

    def stop(self):
        """Stratejiyi ve çalışan tüm WebSocket bağlantılarını durdurur."""
        print(f"🛑 Strateji DURDURULUYOR: '{self.name}' (ID: {self.id})")
        self._stop_event.set()  # Tüm thread'lere durma sinyali gönder
        # Not: websocket-client kütüphanesi thread'leri doğrudan sonlandırmayı desteklemez.
        # Bu sinyal, bağlantı kapandığında yeniden bağlanmayı engeller.

    def _run_websocket(self, symbol):
        """Tek bir sembol için WebSocket'i çalıştıran fonksiyon."""
        stream_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{self.interval}"
        ws = websocket.WebSocketApp(
            stream_url,
            on_open=lambda ws: print(f" Bağlantı açıldı: {symbol} ({self.name})"),
            on_message=lambda ws, msg: self._on_message(ws, msg, symbol),
            on_error=lambda ws, err: print(f"Hata: {symbol} ({self.name}) - {err}"),
            on_close=lambda ws, code, msg: print(f"Bağlantı kapandı: {symbol} ({self.name})")
        )

        while not self._stop_event.is_set():
            ws.run_forever(ping_interval=60, ping_timeout=10)
            if not self._stop_event.is_set():
                print(f"Yeniden bağlanılıyor: {symbol} ({self.name})...")
                time.sleep(5)

    def _on_message(self, ws, message, symbol):
        """WebSocket mesajlarını işleyen ana mantık."""
        data = json.loads(message)
        if 'k' not in data: return

        kline = data['k']
        if not kline['x']: return  # Sadece kapanan mumlarla ilgilen

        print(f"-> Yeni mum: {symbol} ({self.name})")

        # DataFrame'i güncelle
        new_kline_df = pd.DataFrame([{
            "timestamp": pd.to_datetime(kline['t'], unit='ms'), "Open": float(kline['o']),
            "High": float(kline['h']), "Low": float(kline['l']),
            "Close": float(kline['c']), "Volume": float(kline['v']),
        }]).set_index('timestamp')

        df = pd.concat([self.portfolio_data[symbol]['df'], new_kline_df])
        if len(df) > 201:
            df = df.iloc[1:]
        self.portfolio_data[symbol]['df'] = df

        # Göstergeleri ve sinyalleri hesapla
        df_indicators = generate_all_indicators(df, **self.params)
        df_signals = generate_signals(df_indicators, **self.params)

        last_row = df_signals.iloc[-1]
        signal = last_row['Signal']
        price = last_row['Close']

        if signal in ["Al", "Sat"] and self.portfolio_data[symbol]['last_signal'] != signal:
            self.portfolio_data[symbol]['last_signal'] = signal

            message_text = f"🔔 SİNYAL ({self.name})\nSembol: {symbol}\nSinyal: {signal}\nFiyat: {price:.4f} USDT"
            print(f"!!! {message_text} !!!")
            log_alarm(symbol, f"{signal} ({self.name})")

            # Telegram bildirimi (config dosyasından okunabilir, şimdilik sabit)
            # if self.params.get("use_telegram", True):
            #     send_telegram_message(message_text)


# --- Ana Yönetici Döngüsü ---
def main_manager():
    print("🚀 Çoklu Strateji Yöneticisi (Multi-Worker) Başlatıldı.")
    running_strategies = {}  # Çalışan StrategyRunner nesnelerini tutar

    while True:
        try:
            # 1. Strateji dosyasını oku
            with open(STRATEGIES_FILE, 'r') as f:
                strategies_on_disk = json.load(f)

            disk_ids = {s['id'] for s in strategies_on_disk}
            running_ids = set(running_strategies.keys())

            # 2. Yeni eklenen stratejileri başlat
            new_ids = disk_ids - running_ids
            for strategy_config in strategies_on_disk:
                if strategy_config['id'] in new_ids:
                    runner = StrategyRunner(strategy_config)
                    running_strategies[runner.id] = runner
                    runner.start()

            # 3. Silinen stratejileri durdur
            removed_ids = running_ids - disk_ids
            for strategy_id in removed_ids:
                print(f"Strateji '{running_strategies[strategy_id].name}' dosyadan silinmiş, durduruluyor.")
                running_strategies[strategy_id].stop()
                del running_strategies[strategy_id]

        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"HATA: '{STRATEGIES_FILE}' dosyası okunamıyor veya bozuk. Hata: {e}")
        except Exception as e:
            print(f"Yönetici döngüsünde beklenmedik bir hata oluştu: {e}")

        # Kontroller arasında bekle
        time.sleep(5)


if __name__ == "__main__":
    main_manager()