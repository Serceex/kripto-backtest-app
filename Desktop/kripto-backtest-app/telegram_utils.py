# telegram_utils.py
import requests
import logging

def send_telegram_message(message: str, token: str, chat_id: str):
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        response = requests.post(url, data=data)
        response.raise_for_status()
    except Exception as e:
        logging.error(f"Telegram mesaj gönderilemedi: {e}")
