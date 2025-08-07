import sqlite3
import pandas as pd
import json
import threading

DB_NAME = "veritas_point.db"

# Birden fazla thread'in veritabanına aynı anda yazmasını engellemek için kilit
db_lock = threading.Lock()

def get_db_connection():
    """Veritabanı bağlantısı oluşturur ve ayarlar."""
    # check_same_thread=False parametresi, Streamlit ve worker'ın
    # farklı thread'lerden veritabanına erişmesine izin verir.
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def initialize_db():
    """
    Veritabanını ve gerekli tabloları (eğer mevcut değilse) oluşturur.
    Bu fonksiyon, ana uygulamanın başında yalnızca bir kez çağrılmalıdır.
    """
    with db_lock:
        with get_db_connection() as conn:
            cursor = conn.cursor()

            # 1. Stratejileri tutacak tablo
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT,
                symbols TEXT,
                interval TEXT,
                strategy_params TEXT
            )
            """)

            # 2. Açık pozisyonları tutacak tablo (SÖZDİZİMİ DÜZELTİLDİ)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                position TEXT,
                entry_price REAL,
                FOREIGN KEY (strategy_id) REFERENCES strategies (id) ON DELETE CASCADE,
                UNIQUE(strategy_id, symbol)
            )
            """)

            # 3. Alarm geçmişini tutacak tablo
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS alarms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal TEXT,
                price REAL
            )
            """)
            conn.commit()
    print("Veritabanı başarıyla başlatıldı ve tablolar kontrol edildi.")

# --- Strateji Yönetim Fonksiyonları ---

def add_or_update_strategy(strategy_config):
    """Veritabanına yeni bir strateji ekler veya mevcut olanı günceller."""
    params_json = json.dumps(strategy_config.get("strategy_params", {}))
    symbols_json = json.dumps(strategy_config.get("symbols", []))
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO strategies (id, name, status, symbols, interval, strategy_params)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    status=excluded.status,
                    symbols=excluded.symbols,
                    interval=excluded.interval,
                    strategy_params=excluded.strategy_params
            """, (strategy_config['id'], strategy_config['name'], strategy_config.get('status', 'running'),
                  symbols_json, strategy_config['interval'], params_json))
            conn.commit()

def remove_strategy(strategy_id):
    """Veritabanından bir stratejiyi ID'sine göre siler."""
    with db_lock:
        with get_db_connection() as conn:
            # ON DELETE CASCADE sayesinde bu stratejiye bağlı pozisyonlar da silinecektir.
            conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
            conn.commit()

def get_all_strategies():
    """Veritabanındaki tüm stratejileri bir liste olarak döndürür."""
    with db_lock:
        with get_db_connection() as conn:
            strategies = conn.execute("SELECT * FROM strategies").fetchall()
            # Veritabanından gelen JSON string'lerini tekrar Python objelerine çevir
            result = []
            for s in strategies:
                strategy_dict = dict(s)
                strategy_dict['symbols'] = json.loads(s['symbols'])
                strategy_dict['strategy_params'] = json.loads(s['strategy_params'])
                result.append(strategy_dict)
            return result

# --- Pozisyon Yönetim Fonksiyonları ---

def update_position(strategy_id, symbol, position, entry_price):
    """Belirli bir strateji ve sembol için pozisyonu günceller veya ekler."""
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO positions (strategy_id, symbol, position, entry_price)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(strategy_id, symbol) DO UPDATE SET
                    position=excluded.position,
                    entry_price=excluded.entry_price
            """, (strategy_id, symbol, position, entry_price))
            conn.commit()

def get_positions_for_strategy(strategy_id):
    """Bir stratejiye ait tüm pozisyonları sözlük formatında döndürür."""
    with db_lock:
        with get_db_connection() as conn:
            positions = conn.execute("SELECT symbol, position, entry_price FROM positions WHERE strategy_id = ?", (strategy_id,)).fetchall()
            return {p['symbol']: {'position': p['position'], 'entry_price': p['entry_price']} for p in positions}

# --- Alarm Yönetim Fonksiyonları ---

def log_alarm_db(symbol, signal, price):
    """Bir alarmı veritabanına kaydeder."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO alarms (timestamp, symbol, signal, price) VALUES (?, ?, ?, ?)",
                         (timestamp, symbol, signal, price))
            conn.commit()

def get_alarm_history_db(limit=50):
    """Alarm geçmişini veritabanından bir DataFrame olarak okur."""
    with db_lock:
        with get_db_connection() as conn:
            query = "SELECT timestamp as Zaman, symbol as Sembol, signal as Sinyal, price as Fiyat FROM alarms ORDER BY id DESC LIMIT ?"
            df = pd.read_sql_query(query, conn, params=(limit,))
            return df