# multi_worker.py (Hata Yönetimi Güçlendirilmiş Nihai Hali)

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
from telegram_alert import send_telegram_message  # Güvenli hale getirdiğimiz modülü import ediyoruz
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

                self.portfolio_data[symbol] = {'df': initial_df, 'last_signal': None}

                ws_thread = threading.Thread(target=self._run_websocket, args=(symbol,), daemon=True)
                self.ws_threads[symbol] = ws_thread
                ws_thread.start()
                time.sleep(0.5)  # Binance rate limit'e takılmamak için kısa bekleme
            except Exception as e:
                print(f"KRİTİK HATA ({self.name}): {symbol} başlatılırken bir sorun oluştu: {e}")

    def stop(self):
        """Stratejiyi ve çalışan tüm WebSocket bağlantılarını durdurur."""
        print(f"🛑 Strateji DURDURULUYOR: '{self.name}' (ID: {self.id})")
        self._stop_event.set()

    def _run_websocket(self, symbol):
        """Tek bir sembol için WebSocket'i çalıştıran fonksiyon (Gelişmiş Hata Yönetimi ile)."""
        stream_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{self.interval}"

        while not self._stop_event.is_set():
            try:
                ws = websocket.WebSocketApp(
                    stream_url,
                    on_open=lambda ws: print(f" Bağlantı açıldı: {symbol} ({self.name})"),
                    on_message=lambda ws, msg: self._on_message(ws, msg, symbol),
                    on_error=lambda ws, err: print(f"Hata ({self.name}): {symbol} - {err}"),
                    on_close=lambda ws, code, msg: print(f"Bağlantı kapandı: {symbol} ({self.name})")
                )
                ws.run_forever(ping_interval=60, ping_timeout=10)

            except websocket.WebSocketException as e:
                print(f"WebSocket Hatası ({symbol}, {self.name}): {e}. 10 saniye sonra yeniden denenecek.")
            except ConnectionResetError as e:
                print(f"Bağlantı Sıfırlandı ({symbol}, {self.name}): {e}. 10 saniye sonra yeniden denenecek.")
            except Exception as e:
                print(f"Beklenmedik Hata ({symbol}, {self.name}): {e}. 30 saniye sonra yeniden denenecek.")

            if not self._stop_event.is_set():
                time.sleep(10)

    def _on_message(self, ws, message, symbol):
        """WebSocket mesajlarını işleyen ana mantık (Gelişmiş Hata Yönetimi ile)."""
        try:
            data = json.loads(message)
            if 'k' not in data or 'x' not in data['k']:
                return

            kline = data['k']
            if not kline['x']: return # Sadece kapanmış mumlarla işlem yap

            print(f"-> Yeni mum: {symbol} ({self.name})")

            # Gelen yeni veriyi DataFrame formatına hazırla
            new_kline_df = pd.DataFrame([{'timestamp': pd.to_datetime(kline['t'], unit='ms'), 'Open': float(kline['o']),
                                          'High': float(kline['h']), 'Low': float(kline['l']),
                                          'Close': float(kline['c']), 'Volume': float(kline['v']),
                                          }]).set_index('timestamp')

            df = self.portfolio_data[symbol]['df']

            # --- Mükerrer Index Hatası için Düzeltme ---
            # Gelen yeni mumun zaman damgası mevcut DataFrame'de var mı diye kontrol et.
            if new_kline_df.index[0] in df.index:
                # Eğer varsa, mevcut satırı yeni veriyle güncelle. Bu, mükerrer veri eklemeyi önler.
                df.loc[new_kline_df.index] = new_kline_df.values
            else:
                # Eğer yoksa, yeni satırı ekle (concat).
                df = pd.concat([df, new_kline_df])
            # --- Düzeltme Sonu ---

            if len(df) > 201: df = df.iloc[1:]
            self.portfolio_data[symbol]['df'] = df

            df_indicators = generate_all_indicators(df, **self.params)
            df_signals = generate_signals(df_indicators, **self.params)

            last_row = df_signals.iloc[-1]
            signal = last_row['Signal']
            price = last_row['Close']

            if signal in ["Al", "Sat"] and self.portfolio_data[symbol].get('last_signal') != signal:
                self.portfolio_data[symbol]['last_signal'] = signal

                message_text = f"🔔 SİNYAL ({self.name})\nSembol: {symbol}\nSinyal: {signal}\nFiyat: {price:.4f} USDT"
                print(f"!!! {message_text} !!!")
                log_alarm(symbol, f"{signal} ({self.name})")

                # Strateji parametrelerinden telegram ayarlarını alarak güvenli gönderim yap
                if self.params.get("telegram_enabled", False):
                    token = self.params.get("telegram_token")
                    chat_id = self.params.get("telegram_chat_id")
                    if token and chat_id:
                        send_telegram_message(message_text, token, chat_id)

        except json.JSONDecodeError:
            print(f"HATA ({symbol}, {self.name}): Binance'ten gelen veri JSON formatında değil.")
        except KeyError as e:
            print(f"HATA ({symbol}, {self.name}): Gelen veride beklenen anahtar ('{e}') bulunamadı.")
        except Exception as e:
            print(f"KRİTİK HATA ({symbol}, {self.name}): Mesaj işlenirken sorun oluştu: {e}")


# --- Ana Yönetici Döngüsü ---
def main_manager():
    print("🚀 Çoklu Strateji Yöneticisi (Multi-Worker) Başlatıldı.")
    running_strategies = {}

    while True:
        try:
            with open(STRATEGIES_FILE, 'r') as f:
                strategies_on_disk = json.load(f)

            disk_ids = {s['id'] for s in strategies_on_disk}
            running_ids = set(running_strategies.keys())

            # Yeni eklenen stratejileri başlat
            new_ids = disk_ids - running_ids
            for strategy_config in strategies_on_disk:
                if strategy_config['id'] in new_ids:
                    runner = StrategyRunner(strategy_config)
                    running_strategies[runner.id] = runner
                    runner.start()

            # Kaldırılan stratejileri durdur
            removed_ids = running_ids - disk_ids
            for strategy_id in removed_ids:
                if strategy_id in running_strategies:
                    print(f"Strateji '{running_strategies[strategy_id].name}' dosyadan silinmiş, durduruluyor.")
                    running_strategies[strategy_id].stop()
                    del running_strategies[strategy_id]

        except FileNotFoundError:
            print(f"UYARI: '{STRATEGIES_FILE}' bulunamadı. Lütfen arayüzden bir strateji ekleyin.")
            time.sleep(15)
            continue
        except json.JSONDecodeError:
            print(f"HATA: '{STRATEGIES_FILE}' dosyası bozuk veya boş. Okunabilir hale gelmesi bekleniyor.")
        except Exception as e:
            print(f"Yönetici döngüsünde beklenmedik bir hata oluştu: {e}")

        time.sleep(5) # Strateji dosyasını kontrol etme sıklığı


if __name__ == "__main__":
    main_manager()