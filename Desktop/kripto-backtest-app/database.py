# database.py dosyasının yeni, TAM ve DOĞRU içeriği

import sqlite3
import pandas as pd
import json
import threading
import os
from datetime import datetime

try:
    project_dir = os.path.dirname(os.path.abspath(__file__))
    DB_NAME = os.path.join(project_dir, "veritas_point.db")
    print(f"--- [DATABASE] Veritabanı dosya yolu: {DB_NAME} ---")
except Exception as e:
    DB_NAME = "veritas_point.db"
    print(f"--- [HATA] Veritabanı yolu belirlenemedi: {e} ---")

db_lock = threading.Lock()

def get_db_connection():
    """Veritabanı bağlantı nesnesini döndürür."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    """Veritabanını ve tabloları başlangıçta oluşturur."""
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
            # DÜZELTME: alarms tablosuna strategy_id sütunu eklendi.
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT,
                timestamp TEXT,
                symbol TEXT,
                signal TEXT,
                price REAL,
                FOREIGN KEY (strategy_id) REFERENCES strategies (id) ON DELETE CASCADE
            )""")
            conn.commit()
    print("--- [DATABASE] Veritabanı başlatıldı. ---")

def add_or_update_strategy(strategy_config):
    """Veritabanına yeni bir strateji ekler veya mevcut olanı günceller."""
    print("\n--- [DATABASE: YAZMA] add_or_update_strategy çağrıldı. ---")
    try:
        params_json = json.dumps(strategy_config.get("strategy_params", {}))
        symbols_json = json.dumps(strategy_config.get("symbols", []))
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
    """Veritabanından bir stratejiyi ID'sine göre siler."""
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
            conn.commit()
    print(f"--- [DATABASE] Strateji (ID: {strategy_id}) silindi. ---")

def get_all_strategies():
    """Veritabanındaki tüm stratejileri bir liste olarak döndürür."""
    with db_lock:
        with get_db_connection() as conn:
            strategies_raw = conn.execute("SELECT * FROM strategies").fetchall()
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
    return result

def update_position(strategy_id, symbol, position, entry_price):
    """Bir stratejinin pozisyon durumunu veritabanında günceller."""
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
    """Belirli bir stratejiye ait tüm pozisyonları döndürür."""
    with db_lock:
        with get_db_connection() as conn:
            positions = conn.execute("SELECT symbol, position, entry_price FROM positions WHERE strategy_id = ?", (strategy_id,)).fetchall()
            return {p['symbol']: {'position': p['position'], 'entry_price': p['entry_price']} for p in positions}

# DÜZELTME: log_alarm_db fonksiyonu artık strategy_id alacak.
def log_alarm_db(strategy_id, symbol, signal, price):
    """Bir alarmı, ilişkili olduğu strateji ID'si ile birlikte veritabanına kaydeder."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO alarms (strategy_id, timestamp, symbol, signal, price) VALUES (?, ?, ?, ?, ?)",
                         (strategy_id, timestamp, symbol, signal, price))
            conn.commit()
    print(f"--- [DATABASE] Alarm loglandı: Strateji({strategy_id}) - {symbol} - {signal} ---")

# DÜZELTME: Sorgu, artık sadece aktif stratejilere ait alarmları getirecek.
def get_alarm_history_db(limit=50):
    """Sadece veritabanında MEVCUT olan stratejilerden gelen son alarmları döndürür."""
    with db_lock:
        with get_db_connection() as conn:
            # JOIN, bir strateji silindiğinde alarmlarının da gizlenmesini sağlar.
            query = """
                SELECT a.timestamp as Zaman, a.symbol as Sembol, a.signal as Sinyal, a.price as Fiyat
                FROM alarms a
                JOIN strategies s ON a.strategy_id = s.id
                ORDER BY a.id DESC
                LIMIT ?
            """
            df = pd.read_sql_query(query, conn, params=(limit,))
            return df