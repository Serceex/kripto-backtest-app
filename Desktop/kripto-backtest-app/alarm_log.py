import os
import pandas as pd
from datetime import datetime

ALARM_LOG_PATH = "alarm_history.csv"


def log_alarm(symbol, signal):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = pd.DataFrame([[timestamp, symbol, signal]], columns=["Zaman", "Sembol", "Sinyal"])

    if os.path.exists(ALARM_LOG_PATH):
        existing = pd.read_csv(ALARM_LOG_PATH)
        updated = pd.concat([entry, existing], ignore_index=True)
        updated.to_csv(ALARM_LOG_PATH, index=False)
    else:
        entry.to_csv(ALARM_LOG_PATH, index=False)


def get_alarm_history(limit=50):
    if os.path.exists(ALARM_LOG_PATH):
        df = pd.read_csv(ALARM_LOG_PATH)
        return df.tail(limit).iloc[::-1]
    else:
        return pd.DataFrame(columns=["Zaman", "Sembol", "Sinyal"])
