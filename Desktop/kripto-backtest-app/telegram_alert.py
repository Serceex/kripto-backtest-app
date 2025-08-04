# telegram_alert.py (Güvenli ve Güncellenmiş Hali)

import requests
import streamlit as st  # Streamlit secrets'a erişim için eklendi


# telegram_alert.py (Nihai ve Doğru Hali)
import requests

# ARTIK GLOBAL DEĞİŞKEN YOK

def send_telegram_message(message: str, token: str, chat_id: str):
    """
    Telegram'a parametre olarak verilen token ve chat_id ile mesaj gönderir.
    """
    if not token or not chat_id:
        print("Telegram token veya chat_id eksik. Gönderim atlandı.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}

    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Telegram hata: {response.text}")
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")


# Not: send_trade_signal fonksiyonu artık doğrudan send_telegram_message'ı
# kullandığı için ek bir değişikliğe ihtiyaç duymaz.
def send_trade_signal(symbol: str, signal: str, price: float, timestamp: str):
    """
    Al/Sat sinyali için biçimlendirilmiş mesaj gönderimi
    """
    emoji_map = {"Al": "🟢", "Sat": "🔴", "Short": "🔴", "Bekle": "⏸️"}
    emoji = emoji_map.get(signal, "⏸️")
    msg = (
        f"{emoji} *{symbol}* sinyali geldi!\n\n"
        f"📡 Sinyal: *{signal}*\n"
        f"💰 Fiyat: `{price:.2f} USDT`\n"
        f"🕒 Zaman: `{timestamp}`"
    )
    send_telegram_message(msg)