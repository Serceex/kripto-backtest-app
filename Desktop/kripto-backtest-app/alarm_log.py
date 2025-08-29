# alarm_log.py (Veritabanı Entegreli Hali)

# Kendi veritabanı modülümüzden fonksiyonları import ediyoruz
from database import log_alarm_db, get_alarm_history_db
import pandas as pd

def log_alarm(strategy_id: str, symbol: str, signal: str, price: float):
    """
    Alarmı veritabanına kaydeder.
    Strateji ID'si artık bir parametre.
    """
    try:
        log_alarm_db(strategy_id, symbol, signal, price)
    except Exception as e:
        print(f"ALARM DB HATA: Veritabanına yazılırken bir sorun oluştu: {e}")

def get_alarm_history(limit=50):
    """
    Alarm geçmişini veritabanından okur.
    """
    try:
        return get_alarm_history_db(limit)
    except Exception as e:
        print(f"ALARM DB HATA: Veritabanından okunurken bir sorun oluştu: {e}")
        # Hata durumunda boş bir DataFrame döndürerek arayüzün çökmesini engelle
        return pd.DataFrame(columns=["Zaman", "Sembol", "Sinyal", "Fiyat"])