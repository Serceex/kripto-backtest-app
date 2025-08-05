# alarm_log.py (Fiyat Bilgisi Eklenmiş Tam Hali)

import os
import pandas as pd
from datetime import datetime
import threading

# Dosya yazma işlemleri için bir kilit oluşturuyoruz.
file_lock = threading.Lock()

ALARM_LOG_PATH = "alarm_history.csv"


def log_alarm(symbol: str, signal: str, price: float):
    """
    Alarm geçmişini (fiyat bilgisiyle birlikte) bir CSV dosyasına
    thread-safe (iş parçacığı-güvenli) bir şekilde kaydeder.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # DataFrame'e "Fiyat" sütununu ekliyoruz
    entry = pd.DataFrame([[timestamp, symbol, signal, price]], columns=["Zaman", "Sembol", "Sinyal", "Fiyat"])

    # Kilit ile dosya yazma bloğunu koruma altına alıyoruz.
    with file_lock:
        try:
            if os.path.exists(ALARM_LOG_PATH):
                existing = pd.read_csv(ALARM_LOG_PATH)
                updated = pd.concat([entry, existing], ignore_index=True)
                updated.to_csv(ALARM_LOG_PATH, index=False)
            else:
                entry.to_csv(ALARM_LOG_PATH, index=False)
        except Exception as e:
            print(f"ALARM LOG HATA: Dosya yazılırken bir sorun oluştu: {e}")


def get_alarm_history(limit=50):
    """
    Alarm geçmişini okur.
    """
    columns = ["Zaman", "Sembol", "Sinyal", "Fiyat"]
    with file_lock:
        try:
            if os.path.exists(ALARM_LOG_PATH):
                df = pd.read_csv(ALARM_LOG_PATH)
                # Dosya eski formattaysa eksik sütunları ekle
                for col in columns:
                    if col not in df.columns:
                        df[col] = pd.NA
                return df.head(limit)
            else:
                return pd.DataFrame(columns=columns)
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=columns)
        except Exception as e:
            print(f"ALARM LOG HATA: Dosya okunurken bir sorun oluştu: {e}")
            return pd.DataFrame(columns=columns)