# database.py (PostgreSQL Uyumlu Final Hali)

import psycopg2
import psycopg2.extras # Dictionary cursor için gerekli
import pandas as pd
import json
import os
import streamlit as st
from datetime import datetime
import numpy as np

# --- PostgreSQL Bağlantı Bilgileri ---
# Bu bilgileri Streamlit'in secrets.toml dosyasından güvenli bir şekilde alacağız.
try:
    db_config = st.secrets["postgres"]
    DB_NAME = db_config["database"]
    DB_USER = db_config["user"]
    DB_PASSWORD = db_config["password"]
    DB_HOST = db_config["host"]
    DB_PORT = db_config["port"]
except Exception as e:
    print(f"--- [HATA] PostgreSQL bağlantı bilgileri okunamadı. Lütfen .streamlit/secrets.toml dosyasını kontrol edin: {e} ---")
    # Uygulamanın çökmemesi için varsayılan değerler atanabilir veya çıkış yapılabilir.
    st.error("Veritabanı bağlantı bilgileri bulunamadı!")
    st.stop()


def get_db_connection():
    """PostgreSQL veritabanı bağlantı nesnesini döndürür."""
    conn = psycopg2.connect(
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT
    )
    return conn

def initialize_db():
    """Veritabanını ve tabloları başlangıçta oluşturur."""
    # PostgreSQL'in kendi eşzamanlılık yönetimi daha güçlü olduğu için threading.Lock'a gerek yoktur.
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # Strateji tablosu
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT DEFAULT 'running',
                symbols JSONB,
                interval TEXT,
                strategy_params JSONB,
                orchestrator_status TEXT DEFAULT 'active',
                is_trading_enabled BOOLEAN DEFAULT FALSE
            )""")

            # Pozisyonlar tablosu (PostgreSQL'e özel SERIAL PRIMARY KEY kullanımı)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id SERIAL PRIMARY KEY,
                strategy_id TEXT REFERENCES strategies(id) ON DELETE CASCADE,
                symbol TEXT,
                position TEXT,
                entry_price REAL,
                stop_loss_price REAL DEFAULT 0,
                tp1_price REAL DEFAULT 0,
                tp2_price REAL DEFAULT 0,
                tp1_hit BOOLEAN DEFAULT FALSE,
                tp2_hit BOOLEAN DEFAULT FALSE,
                UNIQUE(strategy_id, symbol)
            )""")

            # Alarmlar tablosu
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS alarms (
                id SERIAL PRIMARY KEY,
                strategy_id TEXT REFERENCES strategies(id) ON DELETE CASCADE,
                timestamp TIMESTAMPTZ,
                symbol TEXT,
                signal TEXT,
                price REAL
            )""")

            # Manuel işlemler tablosu
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS manual_actions (
                id SERIAL PRIMARY KEY,
                strategy_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                timestamp TIMESTAMPTZ,
                status TEXT DEFAULT 'pending'
            )""")
        conn.commit()
    print("--- [DATABASE] PostgreSQL veritabanı ve tablolar başarıyla başlatıldı/doğrulandı. ---")

def add_or_update_strategy(strategy_config):
    """Veritabanına yeni bir strateji ekler veya mevcut olanı günceller."""
    params_json = json.dumps(strategy_config.get("strategy_params", {}))
    symbols_json = json.dumps(strategy_config.get("symbols", []))

    sql = """
        INSERT INTO strategies (id, name, status, symbols, interval, strategy_params, orchestrator_status, is_trading_enabled)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name,
            status = EXCLUDED.status,
            symbols = EXCLUDED.symbols,
            interval = EXCLUDED.interval,
            strategy_params = EXCLUDED.strategy_params,
            orchestrator_status = EXCLUDED.orchestrator_status,
            is_trading_enabled = EXCLUDED.is_trading_enabled;
    """
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (
                strategy_config.get('id'), strategy_config.get('name'),
                strategy_config.get('status', 'running'), symbols_json,
                strategy_config.get('interval'), params_json,
                strategy_config.get('orchestrator_status', 'active'),
                strategy_config.get('is_trading_enabled', False)
            ))
        conn.commit()

# ... (Diğer tüm fonksiyonlar benzer şekilde PostgreSQL sözdizimine ('%s') ve mantığına göre güncellenecek)
# Not: Tamlık açısından, diğer tüm fonksiyonları da aşağıda güncelliyorum.

def remove_strategy(strategy_id):
    """Veritabanından bir stratejiyi ID'sine göre siler."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
        conn.commit()
    print(f"--- [DATABASE] Strateji (ID: {strategy_id}) silindi. ---")

def get_all_strategies():
    """Veritabanındaki tüm stratejileri bir liste olarak döndürür."""
    result = []
    with get_db_connection() as conn:
        # psycogp2.extras.DictCursor satırları sözlük gibi kullanmamızı sağlar.
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM strategies")
            strategies_raw = cursor.fetchall()
            for row in strategies_raw:
                # JSONB alanları otomatik olarak dict/list'e dönüşür
                result.append(dict(row))
    return result

def update_position(strategy_id, symbol, position, entry_price, sl_price=0, tp1_price=0, tp2_price=0, tp1_hit=False, tp2_hit=False):
    """Bir stratejinin pozisyon durumunu veritabanında günceller."""
    sql = """
        INSERT INTO positions (strategy_id, symbol, position, entry_price, stop_loss_price, tp1_price, tp2_price, tp1_hit, tp2_hit)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (strategy_id, symbol) DO UPDATE SET
            position = EXCLUDED.position,
            entry_price = EXCLUDED.entry_price,
            stop_loss_price = EXCLUDED.stop_loss_price,
            tp1_price = EXCLUDED.tp1_price,
            tp2_price = EXCLUDED.tp2_price,
            tp1_hit = EXCLUDED.tp1_hit,
            tp2_hit = EXCLUDED.tp2_hit;
    """
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (strategy_id, symbol, position, entry_price, sl_price, tp1_price, tp2_price, tp1_hit, tp2_hit))
        conn.commit()

def get_positions_for_strategy(strategy_id):
    """Belirli bir stratejiye ait tüm pozisyonları döndürür."""
    positions = {}
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM positions WHERE strategy_id = %s", (strategy_id,))
            for row in cursor.fetchall():
                positions[row['symbol']] = dict(row)
    return positions

def log_alarm_db(strategy_id, symbol, signal, price):
    """Bir alarmı veritabanına kaydeder."""
    timestamp = datetime.now()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO alarms (strategy_id, timestamp, symbol, signal, price) VALUES (%s, %s, %s, %s, %s)",
                         (strategy_id, timestamp, symbol, signal, price))
        conn.commit()

def get_alarm_history_db(limit=50):
    """Son alarmları veritabanından bir DataFrame olarak döndürür."""
    with get_db_connection() as conn:
        query = """
            SELECT a.timestamp as "Zaman", a.symbol as "Sembol", a.signal as "Sinyal", a.price as "Fiyat"
            FROM alarms a
            JOIN strategies s ON a.strategy_id = s.id
            ORDER BY a.id DESC
            LIMIT %s
        """
        df = pd.read_sql_query(query, conn, params=(limit,))
    return df

def get_all_open_positions():
    """Tüm açık pozisyonları bir DataFrame olarak döndürür."""
    with get_db_connection() as conn:
        query = """
            SELECT
                s.id as "strategy_id",
                s.name as "Strateji Adı",
                p.symbol as "Sembol",
                p.position as "Pozisyon",
                p.entry_price as "Giriş Fiyatı",
                p.stop_loss_price as "Stop Loss",
                p.tp1_price as "TP1",
                p.tp2_price as "TP2"
            FROM positions p
            JOIN strategies s ON p.strategy_id = s.id
            WHERE p.position IS NOT NULL AND p.position != ''
        """
        df = pd.read_sql_query(query, conn)
    return df

# get_live_closed_trades_metrics ve diğer fonksiyonlar da benzer şekilde güncellenmeli.
# Örnek olarak bir tanesini daha güncelliyorum:
def update_strategy_status(strategy_id, status, is_orchestrator_decision=False):
    """Bir stratejinin durumunu günceller."""
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if is_orchestrator_decision:
                cursor.execute("UPDATE strategies SET orchestrator_status = %s WHERE id = %s", (status, strategy_id))
            else:
                cursor.execute("UPDATE strategies SET status = %s WHERE id = %s", (status, strategy_id))
        conn.commit()

def issue_manual_action(strategy_id, symbol, action):
    """Arayüzden çalışana manuel bir komut gönderir."""
    timestamp = datetime.now()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO manual_actions (strategy_id, symbol, action, timestamp) VALUES (%s, %s, %s, %s)",
                (strategy_id, symbol, action, timestamp)
            )
        conn.commit()

def get_and_clear_pending_actions(strategy_id):
    """Bekleyen komutları alır ve 'tamamlandı' olarak işaretler."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute(
                "SELECT id, symbol, action FROM manual_actions WHERE strategy_id = %s AND status = 'pending'",
                (strategy_id,)
            )
            actions = [dict(row) for row in cursor.fetchall()]

            if actions:
                action_ids = tuple(action['id'] for action in actions)
                # IN operatörü için tuple'ı doğru formatta kullan
                cursor.execute("UPDATE manual_actions SET status = 'completed' WHERE id IN %s", (action_ids,))
        conn.commit()
        return actions