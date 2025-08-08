# database.py dosyasının YENİ ve TAM içeriği

import sqlite3
import pandas as pd
import json
import threading
import os

# --- Projenin mutlak yolunu alarak DB yolunu belirleme (ÖNEMLİ) ---
try:
    project_dir = os.path.dirname(os.path.abspath(__file__))
    DB_NAME = os.path.join(project_dir, "veritas_point.db")
    print(f"--- [DATABASE] Veritabanı dosya yolu: {DB_NAME} ---")
except Exception as e:
    DB_NAME = "veritas_point.db"  # Fallback
    print(f"--- [HATA] Veritabanı yolu belirlenemedi: {e} ---")

db_lock = threading.Lock()


def get_db_connection():
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    # Row factory'yi burada kullanmayıp, okuma sırasında manuel dict yapacağız
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


def add_or_update_strategy(strategy_config):
    """Veritabanına yeni bir strateji ekler veya mevcut olanı günceller."""
    print("\n--- [DATABASE: YAZMA] add_or_update_strategy fonksiyonu çağrıldı. ---")
    print(f"[YAZMA - Adım 1] Gelen strateji verisi: {strategy_config}")

    try:
        params_json = json.dumps(strategy_config.get("strategy_params", {}))
        symbols_json = json.dumps(strategy_config.get("symbols", []))
        print(f"[YAZMA - Adım 2] JSON'a çevrilen parametreler ve semboller BAŞARILI.")
    except Exception as e:
        print(f"[YAZMA - HATA] JSON'a çevirme sırasında hata oluştu: {e}")
        return

    with db_lock:
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
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
                print("[YAZMA - Adım 3] Veritabanına yazma işlemi BAŞARILI.")
        except Exception as e:
            print(f"[YAZMA - HATA] SQL sorgusu çalıştırılırken hata: {e}")


def get_all_strategies():
    """Veritabanındaki tüm stratejileri bir liste olarak döndürür."""
    print("\n--- [DATABASE: OKUMA] get_all_strategies fonksiyonu çağrıldı. ---")
    with db_lock:
        with get_db_connection() as conn:
            conn.row_factory = sqlite3.Row  # Sadece bu fonksiyon için Row factory kullan
            cursor = conn.cursor()
            strategies_raw = cursor.execute("SELECT * FROM strategies").fetchall()

    print(f"[OKUMA - Adım 1] Veritabanından çekilen HAM VERİ (Satır sayısı: {len(strategies_raw)}): {strategies_raw}")

    result = []
    if not strategies_raw:
        print("[OKUMA - Adım 2] Veritabanından hiç strateji verisi gelmedi. Boş liste döndürülüyor.")
        return []

    for s_row in strategies_raw:
        try:
            strategy_dict = dict(s_row)  # sqlite3.Row objesini dict'e çevir
            print(f"[OKUMA - Adım 2] İşlenen satır: {strategy_dict}")

            # JSON string'lerini Python objelerine çevir
            strategy_dict['symbols'] = json.loads(strategy_dict.get('symbols', '[]') or '[]')
            strategy_dict['strategy_params'] = json.loads(strategy_dict.get('strategy_params', '{}') or '{}')

            result.append(strategy_dict)
            print(f"[OKUMA - Adım 3] '{strategy_dict.get('name')}' adlı strateji başarıyla işlendi.")
        except Exception as e:
            print(f"[OKUMA - HATA] Bir strateji satırı işlenirken hata oluştu (ID: {s_row['id']}): {e}")
            # Hatalı satırı atla ama diğerlerini işlemeye devam et
            continue

    print(f"[OKUMA - Adım 4] Fonksiyondan döndürülen nihai sonuç: {result}")
    return result


# Kalan diğer fonksiyonlar (pozisyon, alarm vs.) aynı kalabilir...
# (Buraya alarm_log.py ve diğer dosyalardaki fonksiyonları kopyalamaya gerek yok, sadece yukarıdaki 3 fonksiyonu güncelleyin)

def remove_strategy(strategy_id):
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM strategies WHERE id = ?", (strategy_id,))
            conn.commit()
    print(f"--- [DATABASE] Strateji (ID: {strategy_id}) silindi. ---")