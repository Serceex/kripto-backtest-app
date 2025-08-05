# telegram_alert.py (Güvenli ve Güncellenmiş Nihai Hali)

import requests
import logging

# Hata günlüğü için temel yapılandırma
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def send_telegram_message(message: str, token: str, chat_id: str):
    """
    Telegram'a parametre olarak verilen token ve chat_id ile mesaj gönderir.
    Hata durumlarını loglar.
    """
    if not token or not chat_id:
        logging.warning("Telegram token veya chat_id eksik. Mesaj gönderimi atlandı.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()  # HTTP hata kodları için bir exception fırlatır (4xx veya 5xx)
    except requests.exceptions.RequestException as e:
        logging.error(f"Telegram mesajı gönderilemedi: {e}")
    except Exception as e:
        logging.error(f"Telegram gönderimi sırasında beklenmedik bir hata oluştu: {e}")


def send_trade_signal(symbol: str, signal: str, price: float, token: str, chat_id: str):
    """
    Al/Sat sinyali için biçimlendirilmiş bir mesaj hazırlar ve gönderir.
    """
    emoji_map = {"Al": "🟢", "Sat": "🔴", "Short": "🔴", "Bekle": "⏸️"}
    emoji = emoji_map.get(signal, "🎯")  # Bilinmeyen sinyaller için varsayılan emoji

    # Zaman damgası eklemek yerine mesajı daha sade tutabiliriz
    # veya anlık zamanı kullanabiliriz. Şimdilik sade bırakalım.
    msg = (
        f"{emoji} *{symbol} Sinyali*\n\n"
        f"📡 **Sinyal:** `{signal}`\n"
        f"💰 **Fiyat:** `{price:.4f} USDT`"
    )

    send_telegram_message(msg, token, chat_id)