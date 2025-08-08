# database.py dosyasının yeni, TAM ve DOĞRU içeriği

import sqlite3
import pandas as pd
import json
import threading
import os
from datetime import datetime # Alarm log için eklendi

# --- Projenin mutlak yolunu alarak DB yolunu belirleme ---
try:
    project_dir = os.path.dirname(os.path.abspath(__file__))
    DB_NAME = os.path.join(project_dir, "veritas_point.db")
    print(f"--- [DATABASE] Veritabanı dosya yolu: {DB_NAME} ---")
except Exception as e:
    DB_NAME = "veritas_point.db"
    print(f"--- [HATA] Veritabanı yolu belirlenemedi: {e} ---")

db_lock = threading.Lock()

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    with db_lock:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY, name TEXT, status TEXT,
                symbols TEXT, interval TEXT, strategy_params TEXT
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, strategy_id TEXT, symbol TEXT,
                position TEXT, entry_price REAL,
                FOREIGN KEY (strategy_id) REFERENCES strategies (id) ON DELETE CASCADE,
                UNIQUE(strategy_id, symbol)
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
                symbol TEXT, signal TEXT, price REAL
            )""")
            conn.commit()
    print("--- [DATABASE] Veritabanı başlatıldı. ---")

# --- Strateji Yönetim Fonksiyonları ---

def add_or_update_strategy(strategy_config):
    print("\n--- [DATABASE: YAZMA] add_or_update_strategy çağrıldı. ---")
    print(f"[YAZMA - Adım 1] Gelen strateji verisi: {strategy_config}")
    try:
        params_json = json.dumps(strategy_config.get("strategy_params", {}))
        symbols_json = json.dumps(strategy_config.get("symbols", []))
        print(f"[YAZMA - Adım 2] JSON'a çevirme BAŞARILI.")
    except Exception as e:
        print(f"[YAZMA - HATA] JSON'a çevirme sırasında hata: {e}")
        return
    with db_lock:
        try:
            with get_db_connection() as conn:
                conn.execute("""
                    INSERT INTO strategies (id, name, status, symbols, interval, strategy_params)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name, status=excluded.status, symbols=excluded.symbols,
                        interval=excluded.interval, strategy_params=excluded.strategy_params
                """, (
                    strategy_config.get('id'), strategy_config.get('name'),
                    strategy_config.get('status', 'running'), symbols_json,
                    strategy_config.get('interval'), params_json
                ))
                conn.commit()
                print("[YAZMA - Adım 3] Veritabanına yazma BAŞARILI.")
        except Exception as e:
            print(f"[YAZMA - HATA] SQL sorgusunda hata: {e}")

def remove_strategy(strategy_id):
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
            conn.commit()
    print(f"--- [DATABASE] Strateji (ID: {strategy_id}) silindi. ---")

def get_all_strategies():
    print("\n--- [DATABASE: OKUMA] get_all_strategies çağrıldı. ---")
    with db_lock:
        with get_db_connection() as conn:
            strategies_raw = conn.execute("SELECT * FROM strategies").fetchall()
    print(f"[OKUMA - Adım 1] Veritabanından çekilen HAM VERİ (Satır sayısı: {len(strategies_raw)})")
    result = []
    if not strategies_raw:
        return []
    for s_row in strategies_raw:
        try:
            strategy_dict = dict(s_row)
            strategy_dict['symbols'] = json.loads(strategy_dict.get('symbols', '[]') or '[]')
            strategy_dict['strategy_params'] = json.loads(strategy_dict.get('strategy_params', '{}') or '{}')
            result.append(strategy_dict)
        except Exception as e:
            print(f"[OKUMA - HATA] Bir strateji işlenirken hata (ID: {s_row.get('id')}): {e}")
            continue
    print(f"[OKUMA - Adım 4] Fonksiyondan döndürülen nihai sonuç: {result}")
    return result

# --- Pozisyon Yönetim Fonksiyonları (EKSİK OLAN KISIM) ---

def update_position(strategy_id, symbol, position, entry_price):
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO positions (strategy_id, symbol, position, entry_price)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(strategy_id, symbol) DO UPDATE SET
                    position=excluded.position, entry_price=excluded.entry_price
            """, (strategy_id, symbol, position, entry_price))
            conn.commit()

def get_positions_for_strategy(strategy_id):
    with db_lock:
        with get_db_connection() as conn:
            positions = conn.execute("SELECT symbol, position, entry_price FROM positions WHERE strategy_id = ?", (strategy_id,)).fetchall()
            return {p['symbol']: {'position': p['position'], 'entry_price': p['entry_price']} for p in positions}

# --- Alarm Yönetim Fonksiyonları (EKSİK OLAN KISIM) ---

def log_alarm_db(symbol, signal, price):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO alarms (timestamp, symbol, signal, price) VALUES (?, ?, ?, ?)",
                         (timestamp, symbol, signal, price))
            conn.commit()
    print(f"--- [DATABASE] Alarm loglandı: {symbol} - {signal} ---")

def get_alarm_history_db(limit=50):
    with db_lock:
        with get_db_connection() as conn:
            query = "SELECT timestamp as Zaman, symbol as Sembol, signal as Sinyal, price as Fiyat FROM alarms ORDER BY id DESC LIMIT ?"
            df = pd.read_sql_query(query, conn, params=(limit,))
            return df