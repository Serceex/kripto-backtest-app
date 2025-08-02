import time
import json
import pandas as pd

# Projenizdeki diğer modüllerden gerekli fonksiyonları import ediyoruz
from utils import get_binance_klines
from indicators import generate_all_indicators
from signals import generate_signals
from telegram_alert import send_telegram_message
from alarm_log import log_alarm

CONFIG_FILE = "config.json"
# Sinyallerin tekrar tekrar gönderilmesini engellemek için son gönderilen sinyali saklar
last_signals = {}


def load_config():
    """config.json dosyasından ayarları yükler."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"HATA: {CONFIG_FILE} bulunamadı. Lütfen dosyayı oluşturun.")
        return None
    except json.JSONDecodeError:
        print(f"HATA: {CONFIG_FILE} içinde geçersiz JSON formatı.")
        return None


def main_loop():
    """Ana sinyal takip döngüsü."""
    print("Sinyal takip motoru (worker) başlatıldı.")

    while True:
        config = load_config()
        if not config:
            time.sleep(60)  # Eğer config dosyası okunamıyorsa 1 dakika bekle
            continue

        if not config.get("live_tracking_enabled", False):
            # Streamlit arayüzünden canlı takip kapatılmışsa, döngü beklemeye geçer.
            time.sleep(15)
            continue

        print(f"Ayarlar yüklendi. Takipteki semboller: {config['symbols']}")

        symbols = config["symbols"]
        interval = config["interval"]
        strategy_params = config["strategy_params"]
        telegram_enabled = config.get("telegram_enabled", False)

        for symbol in symbols:
            try:
                print(f"-> {symbol} için veri çekiliyor ve analiz ediliyor...")

                # 1. Veriyi çek
                df = get_binance_klines(symbol, interval, limit=200)  # Analiz için yeterli bar sayısı
                if df is None or df.empty:
                    print(f"HATA: {symbol} için veri alınamadı.")
                    continue

                # 2. Göstergeleri hesapla
                # Not: generate_all_indicators fonksiyonu strateji parametrelerini alacak şekilde güncellenmeli.
                # Şimdilik mevcut halini kullanıyoruz.
                df = generate_all_indicators(df,
                                             sma_period=strategy_params['sma'],
                                             ema_period=strategy_params['ema'],
                                             bb_period=strategy_params['bb_period'],
                                             bb_std=strategy_params['bb_std'],
                                             rsi_period=strategy_params['rsi_period'],
                                             macd_fast=strategy_params['macd_fast'],
                                             macd_slow=strategy_params['macd_slow'],
                                             macd_signal=strategy_params['macd_signal'],
                                             adx_period=strategy_params['adx_period'])

                # 3. Sinyalleri üret
                df = generate_signals(df, **strategy_params)

                # 4. Son sinyali kontrol et
                last_row = df.iloc[-1]
                current_signal = last_row['Signal']
                last_price = last_row['Close']

                # Eğer sinyal "Al" veya "Sat" ise ve bu sembol için önceki sinyalden farklıysa işlem yap
                if current_signal in ["Al", "Sat"] and last_signals.get(symbol) != current_signal:

                    message = f"🔔 YENİ SİNYAL: {symbol}\nSinyal: {current_signal}\nFiyat: {last_price:.4f} USDT"
                    print(f"!!! {message} !!!")

                    # Alarmı kaydet
                    log_alarm(symbol, current_signal)

                    # Telegram'a bildirim gönder
                    if telegram_enabled:
                        send_telegram_message(message)
                        print("-> Telegram bildirimi gönderildi.")

                    # Son gönderilen sinyali güncelle
                    last_signals[symbol] = current_signal

                # Her sembol arasında kısa bir bekleme
                time.sleep(5)

            except Exception as e:
                print(f"HATA: {symbol} işlenirken bir sorun oluştu: {e}")

        # Tüm semboller kontrol edildikten sonra bekleme süresi
        print("Tüm semboller kontrol edildi. 60 saniye bekleniyor...")
        time.sleep(60)


if __name__ == "__main__":
    main_loop()