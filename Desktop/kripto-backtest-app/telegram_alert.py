import requests

# Telegram bot token ve chat_id bilgilerini ayarlayın
TELEGRAM_TOKEN = "8144073534:AAHH8R79sAfoV6qjeHxuCAt1pYHq4Ezg9EY"
CHAT_ID = "1012868061"

def send_telegram_message(message: str):
    """
    Telegram'a düz metin mesaj gönderir.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }

    try:
        response = requests.post(url, json=payload)
        if response.status_code != 200:
            print(f"Telegram hata: {response.text}")
    except Exception as e:
        print(f"Telegram gönderim hatası: {e}")

def send_trade_signal(symbol: str, signal: str, price: float, timestamp: str):
    """
    Al/Sat sinyali için biçimlendirilmiş mesaj gönderimi
    """
    emoji_map = {
        "Al": "🟢",
        "Sat": "🔴",
        "Short": "🔴",
        "Bekle": "⏸️"
    }

    emoji = emoji_map.get(signal, "⏸️")
    msg = (
        f"{emoji} *{symbol}* sinyali geldi!\n\n"
        f"📡 Sinyal: *{signal}*\n"
        f"💰 Fiyat: `{price:.2f} USDT`\n"
        f"🕒 Zaman: `{timestamp}`"
    )
    send_telegram_message(msg)
