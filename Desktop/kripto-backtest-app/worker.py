# worker.py (Yeniden Düzenlenmiş Hali)

import websocket
import json
import pandas as pd
import time
import threading
from datetime import datetime

# Proje modüllerinden gerekli fonksiyonları import ediyoruz
from utils import get_binance_klines
from indicators import generate_all_indicators
from signals import generate_signals
from telegram_alert import send_telegram_message
from alarm_log import log_alarm

CONFIG_FILE = "config.json"

# Takip edilen her sembolün verisini ve son sinyalini saklamak için bir sözlük
portfolio_data = {}


def load_config():
    """config.json dosyasından ayarları yükler."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        print(f"HATA: {CONFIG_FILE} bulunamadı veya formatı bozuk.")
        return None


def on_message(ws, message, symbol):
    """WebSocket'ten bir mesaj (yeni mum verisi) geldiğinde çalışır."""
    global portfolio_data

    data = json.loads(message)['k']
    is_kline_closed = data['x']

    # Sadece mum kapandığında işlem yap
    if is_kline_closed:
        print(f"-> {symbol} için yeni mum geldi. Analiz ediliyor...")

        # Gelen yeni veriyi DataFrame formatına hazırla
        new_kline = {
            "timestamp": pd.to_datetime(data['t'], unit='ms'),
            "Open": float(data['o']),
            "High": float(data['h']),
            "Low": float(data['l']),
            "Close": float(data['c']),
            "Volume": float(data['v']),
        }

        # Mevcut veri setine yenisini ekle, en eskisini çıkar
        df = portfolio_data[symbol]['df']

        # Yeni satırı eklemek için DataFrame oluştur ve concat kullan
        new_row_df = pd.DataFrame([new_kline]).set_index('timestamp')
        df = pd.concat([df, new_row_df])

        # Veri setini belirli bir uzunlukta tut (örneğin son 201 bar)
        if len(df) > 201:
            df = df.iloc[1:]

        portfolio_data[symbol]['df'] = df

        # --- Analiz ve Sinyal Üretimi ---
        config = load_config()
        if not config:
            return

        strategy_params = config["strategy_params"]
        telegram_enabled = config.get("telegram_enabled", False)

        # 2. Göstergeleri hesapla
        df_with_indicators = generate_all_indicators(df, **strategy_params)

        # 3. Sinyalleri üret
        df_with_signals = generate_signals(df_with_indicators, **strategy_params)

        # 4. Son sinyali kontrol et
        last_row = df_with_signals.iloc[-1]
        current_signal = last_row['Signal']
        last_price = last_row['Close']

        # Eğer sinyal "Al" veya "Sat" ise ve bu sembol için önceki sinyalden farklıysa işlem yap
        if current_signal in ["Al", "Sat"] and portfolio_data[symbol].get('last_signal') != current_signal:

            message_text = f"🔔 YENİ SİNYAL: {symbol}\nSinyal: {current_signal}\nFiyat: {last_price:.4f} USDT"
            print(f"!!! {message_text} !!!")

            # Alarmı kaydet
            log_alarm(symbol, current_signal)

            # Telegram'a bildirim gönder
            if telegram_enabled:
                send_telegram_message(message_text)
                print("-> Telegram bildirimi gönderildi.")

            # Son gönderilen sinyali güncelle
            portfolio_data[symbol]['last_signal'] = current_signal
        else:
            print(f"-> {symbol} için yeni sinyal yok. Mevcut Sinyal: {current_signal}")


def on_error(ws, error):
    print(f"WebSocket Hatası: {error}")


def on_close(ws, close_status_code, close_msg):
    print("WebSocket Bağlantısı Kapandı. Yeniden başlatılacak...")
    # Bağlantı kapanırsa, bir süre sonra yeniden başlatmak için mekanizma eklenebilir.
    time.sleep(10)
    main()  # Yeniden başlat


def on_open(ws, symbol):
    print(f"✅ {symbol} için WebSocket bağlantısı kuruldu.")


def start_websocket_for_symbol(symbol, interval):
    """Belirtilen sembol için bir WebSocket bağlantısı başlatır."""
    stream_url = f"wss://stream.binance.com:9443/ws/{symbol.lower()}@kline_{interval}"
    ws = websocket.WebSocketApp(
        stream_url,
        on_message=lambda ws, msg: on_message(ws, msg, symbol),
        on_error=on_error,
        on_close=on_close,
        on_open=lambda ws: on_open(ws, symbol)
    )
    ws.run_forever()


def main():
    """Ana başlangıç fonksiyonu."""
    global portfolio_data

    print("Sinyal takip motoru (worker) başlatılıyor...")

    while True:
        config = load_config()
        if not config:
            time.sleep(60)
            continue

        if not config.get("live_tracking_enabled", False):
            print("Canlı takip arayüzden kapatılmış. 15 saniye bekleniyor...")
            time.sleep(15)
            continue

        symbols = config["symbols"]
        interval = config["interval"]

        threads = []
        for symbol in symbols:
            # Eğer sembol zaten takip edilmiyorsa, başlangıç verisini çek ve thread'i başlat
            if symbol not in portfolio_data or not portfolio_data[symbol].get('is_running', False):
                print(f"-> {symbol} için başlangıç verisi çekiliyor...")
                initial_df = get_binance_klines(symbol, interval, limit=200)
                if initial_df is None or initial_df.empty:
                    print(f"HATA: {symbol} için başlangıç verisi alınamadı.")
                    continue

                portfolio_data[symbol] = {
                    'df': initial_df,
                    'last_signal': None,
                    'is_running': True
                }

                # Her sembol için ayrı bir thread'de websocket'i başlat
                thread = threading.Thread(target=start_websocket_for_symbol, args=(symbol, interval))
                thread.daemon = True  # Ana program kapandığında thread'in de kapanmasını sağlar
                threads.append(thread)
                thread.start()

        # Bu döngü sadece yeni semboller eklendiğinde veya ayarlar değiştiğinde
        # tekrar çalışacak. Mevcut thread'ler çalışmaya devam edecek.
        print("Tüm semboller için WebSocket'ler başlatıldı. Ayar değişiklikleri bekleniyor...")
        time.sleep(60)  # Ayar dosyasını ne sıklıkla kontrol edeceğini belirler.


if __name__ == "__main__":
    main()