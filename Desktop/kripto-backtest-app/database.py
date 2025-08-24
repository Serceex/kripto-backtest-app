# database.py (PostgreSQL Uyumlu - Hata Ayıklama Versiyonu)

import psycopg2
import psycopg2.extras
import pandas as pd
import json
import os
from datetime import datetime
import numpy as np
import toml
import io



DB_CONFIG = None

def get_db_secrets():
    global DB_CONFIG
    if DB_CONFIG is not None:
        return DB_CONFIG

    # 1. Streamlit secrets'ı dene (Streamlit ortamı için)
    try:
        import streamlit as st
        DB_CONFIG = st.secrets["postgres"]
        print("--- [DEBUG] Streamlit secrets başarıyla okundu.")
        return DB_CONFIG
    except Exception:
        print("--- [BİLGİ] Streamlit secrets ortamı değil. .streamlit/secrets.toml dosyası okunacak.")

    # 2. .streamlit/secrets.toml dosyasını doğrudan oku (Worker ortamı için)
    try:
        # secrets.toml dosyasının tam yolunu bul
        # Bu script'in (database.py) bulunduğu dizini al
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Bir üst dizine çıkıp .streamlit/secrets.toml yolunu oluştur
        secrets_path = os.path.join(script_dir, '.streamlit', 'secrets.toml')

        secrets = toml.load(secrets_path)
        DB_CONFIG = secrets["postgres"]
        print("--- [DEBUG] .streamlit/secrets.toml dosyası başarıyla okundu.")
        return DB_CONFIG
    except Exception as e:
        print(f"--- [KRİTİK HATA] secrets.toml dosyası okunamadı veya 'postgres' bölümü bulunamadı: {e}")
        DB_CONFIG = {} # Hata durumunda boş döndür
        return DB_CONFIG

def get_db_connection():
    config = get_db_secrets()
    if not config:
        print("--- [HATA] Veritabanı yapılandırması bulunamadı. Bağlantı kurulamıyor.")
        return None

    try:
        conn = psycopg2.connect(
            dbname=config["database"],
            user=config["user"],
            password=config["password"],
            host=config["host"],
            port=config.get("port", "5432"),
            connect_timeout=5  # 5 saniye zaman aşımı ekledik!
        )
        return conn
    except psycopg2.OperationalError as e:
        print("--- [KRİTİK BAĞLANTI HATASI] ---")
        print(f"PostgreSQL veritabanına bağlanılamadı. Hata: {e}")
        print("Lütfen .streamlit/secrets.toml dosyasındaki bilgilerin (host, port, user, password) doğruluğunu ve veritabanı sunucusunun çalıştığını kontrol edin.")
        print("Ayrıca bir güvenlik duvarının (firewall) bağlantıyı engellemediğinden emin olun.")
        # Streamlit ortamında ise kullanıcıya göster
        try:
            import streamlit as st
            st.error(f"VERİTABANI BAĞLANTI HATASI: {e}")
            st.info("Lütfen .streamlit/secrets.toml dosyanızdaki PostgreSQL bağlantı bilgilerinizi kontrol edin.")
            st.stop()
        except ImportError:
            # Worker'da ise programdan çık
            exit()
        return None


# --- initialize_db ve diğer tüm fonksiyonlar aynı kalabilir ---
# Fonksiyonların geri kalanını okunabilirlik için ekliyorum.

def initialize_db():
    print("--- [DEBUG] initialize_db fonksiyonu çağrıldı.")
    try:
        with get_db_connection() as conn:
            if conn is None: raise Exception("Veritabanı bağlantısı yok.")
            with conn.cursor() as cursor:
                cursor.execute("""
                                CREATE TABLE IF NOT EXISTS strategies (
                                    id TEXT PRIMARY KEY, name TEXT, status TEXT, symbols JSONB, interval TEXT,
                                    strategy_params JSONB, orchestrator_status TEXT, is_trading_enabled BOOLEAN,
                                    rl_model_id INTEGER DEFAULT NULL
                                )""")
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id SERIAL PRIMARY KEY, strategy_id TEXT, symbol TEXT, position TEXT, entry_price REAL,
                    stop_loss_price REAL, tp1_price REAL, tp2_price REAL, tp1_hit BOOLEAN, tp2_hit BOOLEAN,
                    UNIQUE(strategy_id, symbol)
                )""")
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS alarms (
                    id SERIAL PRIMARY KEY, strategy_id TEXT, timestamp TIMESTAMPTZ,
                    symbol TEXT, signal TEXT, price REAL
                )""")
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS manual_actions (
                    id SERIAL PRIMARY KEY, strategy_id TEXT, symbol TEXT, action TEXT,
                    timestamp TIMESTAMPTZ, status TEXT
                )""")
                cursor.execute("""
                                CREATE TABLE IF NOT EXISTS rl_models (
                                    id SERIAL PRIMARY KEY,
                                    name TEXT UNIQUE NOT NULL,
                                    description TEXT,
                                    model_data BYTEA NOT NULL,
                                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                                )""")
            conn.commit()
        print("--- [DATABASE] PostgreSQL veritabanı ve tablolar başarıyla başlatıldı/doğrulandı. ---")
    except Exception as e:
        print(f"--- [KRİTİK HATA] Veritabanı başlatılamadı: {e} ---")


# --- YENİ FONKSİYONLAR: RL Modellerini Yönetmek İçin ---

def save_rl_model(name, description, model_buffer):
    """Eğitilmiş bir RL modelini veritabanına kaydeder."""
    model_data_binary = psycopg2.Binary(model_buffer.getvalue())
    sql = """
        INSERT INTO rl_models (name, description, model_data)
        VALUES (%s, %s, %s)
        ON CONFLICT (name) DO UPDATE SET
            model_data = EXCLUDED.model_data,
            description = EXCLUDED.description,
            created_at = CURRENT_TIMESTAMP;
    """
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (name, description, model_data_binary))
        conn.commit()
    print(f"--- [DATABASE] RL Modeli '{name}' başarıyla kaydedildi/güncellendi. ---")

def get_rl_model_by_id(model_id):
    """Bir RL modelini ID'sine göre veritabanından çeker."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT model_data FROM rl_models WHERE id = %s", (model_id,))
            result = cursor.fetchone()
            if result:
                # BYTEA verisini bir hafıza buffer'ına yükle
                return io.BytesIO(result['model_data'])
    return None

def get_all_rl_models_info():
    """Tüm RL modellerinin bilgilerini (ID ve İsim) listeler."""
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT id, name, description, created_at FROM rl_models ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]


def add_or_update_strategy(strategy_config):
    # rl_model_id'yi None olarak ayarla, eğer varsa integer'a çevir
    rl_model_id = strategy_config.get('rl_model_id')
    if rl_model_id is not None:
        try:
            rl_model_id = int(rl_model_id)
        except (ValueError, TypeError):
            rl_model_id = None

    params_json = json.dumps(strategy_config.get("strategy_params", {}))
    symbols_json = json.dumps(strategy_config.get("symbols", []))
    sql = """
        INSERT INTO strategies (id, name, status, symbols, interval, strategy_params, orchestrator_status, is_trading_enabled, rl_model_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            name = EXCLUDED.name, status = EXCLUDED.status, symbols = EXCLUDED.symbols, interval = EXCLUDED.interval,
            strategy_params = EXCLUDED.strategy_params, orchestrator_status = EXCLUDED.orchestrator_status,
            is_trading_enabled = EXCLUDED.is_trading_enabled, rl_model_id = EXCLUDED.rl_model_id;
    """
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (
                strategy_config.get('id'), strategy_config.get('name'),
                strategy_config.get('status', 'running'), symbols_json,
                strategy_config.get('interval'), params_json,
                strategy_config.get('orchestrator_status', 'active'),
                strategy_config.get('is_trading_enabled', False),
                rl_model_id
            ))
        conn.commit()

def remove_strategy(strategy_id):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
        conn.commit()
    print(f"--- [DATABASE] Strateji (ID: {strategy_id}) silindi. ---")

def get_all_strategies():
    result = []
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM strategies")
            strategies_raw = cursor.fetchall()
            for row in strategies_raw:
                result.append(dict(row))
    return result

def update_position(strategy_id, symbol, position, entry_price, sl_price=0, tp1_price=0, tp2_price=0, tp1_hit=False, tp2_hit=False):
    sql = """
        INSERT INTO positions (strategy_id, symbol, position, entry_price, stop_loss_price, tp1_price, tp2_price, tp1_hit, tp2_hit)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (strategy_id, symbol) DO UPDATE SET
            position = EXCLUDED.position, entry_price = EXCLUDED.entry_price, stop_loss_price = EXCLUDED.stop_loss_price,
            tp1_price = EXCLUDED.tp1_price, tp2_price = EXCLUDED.tp2_price, tp1_hit = EXCLUDED.tp1_hit,
            tp2_hit = EXCLUDED.tp2_hit;
    """
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, (strategy_id, symbol, position, entry_price, sl_price, tp1_price, tp2_price, tp1_hit, tp2_hit))
        conn.commit()

def get_positions_for_strategy(strategy_id):
    positions = {}
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM positions WHERE strategy_id = %s", (strategy_id,))
            for row in cursor.fetchall():
                positions[row['symbol']] = dict(row)
    return positions

def log_alarm_db(strategy_id, symbol, signal, price):
    timestamp = datetime.now()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO alarms (strategy_id, timestamp, symbol, signal, price) VALUES (%s, %s, %s, %s, %s)",
                         (strategy_id, timestamp, symbol, signal, price))
        conn.commit()

def get_alarm_history_db(limit=50):
    with get_db_connection() as conn:
        query = """
            SELECT a.timestamp as "Zaman", a.symbol as "Sembol", a.signal as "Sinyal", a.price as "Fiyat"
            FROM alarms a JOIN strategies s ON a.strategy_id = s.id
            ORDER BY a.id DESC LIMIT %s
        """
        df = pd.read_sql_query(query, conn, params=(limit,))
    return df

def get_all_open_positions():
    with get_db_connection() as conn:
        query = """
            SELECT s.id as "strategy_id", s.name as "Strateji Adı", p.symbol as "Sembol", p.position as "Pozisyon",
                   p.entry_price as "Giriş Fiyatı", p.stop_loss_price as "Stop Loss", p.tp1_price as "TP1", p.tp2_price as "TP2"
            FROM positions p JOIN strategies s ON p.strategy_id = s.id
            WHERE p.position IS NOT NULL AND p.position != ''
        """
        df = pd.read_sql_query(query, conn)
    return df

def update_strategy_status(strategy_id, status, is_orchestrator_decision=False):
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            if is_orchestrator_decision:
                cursor.execute("UPDATE strategies SET orchestrator_status = %s WHERE id = %s", (status, strategy_id))
            else:
                cursor.execute("UPDATE strategies SET status = %s WHERE id = %s", (status, strategy_id))
        conn.commit()

def issue_manual_action(strategy_id, symbol, action):
    timestamp = datetime.now()
    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            # 'status' sütununu 'pending' olarak ekliyoruz
            cursor.execute("INSERT INTO manual_actions (strategy_id, symbol, action, timestamp, status) VALUES (%s, %s, %s, %s, %s)",
                         (strategy_id, symbol, action, timestamp, 'pending'))
        conn.commit()

def get_and_clear_pending_actions(strategy_id):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT id, symbol, action FROM manual_actions WHERE strategy_id = %s AND status = 'pending'",
                         (strategy_id,))
            actions = [dict(row) for row in cursor.fetchall()]
            if actions:
                action_ids = tuple(action['id'] for action in actions)
                cursor.execute("UPDATE manual_actions SET status = 'completed' WHERE id IN %s", (action_ids,))
        conn.commit()
        return actions


def get_live_closed_trades_metrics(strategy_id=None):
    """
    Canlıda kapanan işlemlerin detaylı metriklerini, kademeli kâr alımını (TP1/TP2)
    doğru bir şekilde hesaba katarak hesaplar.
    """
    from database import get_all_strategies
    default_metrics = {
        "Toplam İşlem": 0, "Başarı Oranı (%)": 0.0, "Toplam Getiri (%)": 0.0,
        "Ortalama Kazanç (%)": 0.0, "Ortalama Kayıp (%)": 0.0, "Profit Factor": 0.0
    }

    # Strateji parametrelerini (tp1_size_pct gibi) alabilmek için tüm stratejileri çek
    all_strategies = {s['id']: s for s in get_all_strategies()}

    with get_db_connection() as conn:
        base_query = "SELECT strategy_id, symbol, signal, price, timestamp FROM alarms WHERE "
        # Sadece pozisyon açan ve kapatan sinyalleri al
        conditions = "(signal LIKE '%%Yeni%%' OR signal LIKE '%%Kapatıldı%%' OR signal LIKE '%%Stop-Loss%%' OR signal LIKE '%%Karşıt Sinyal%%')"

        if strategy_id:
            query = base_query + "strategy_id = %s AND " + conditions + " ORDER BY timestamp ASC"
            params = (strategy_id,)
        else:
            query = base_query + conditions + " ORDER BY timestamp ASC"
            params = ()

        df = pd.read_sql_query(query, conn, params=params)

    if df.empty:
        return default_metrics

    trades = []
    open_trades = {}

    for _, row in df.iterrows():
        key = (row['strategy_id'], row['symbol'])
        signal = row['signal']
        price = row['price']
        strategy_id_current = row['strategy_id']

        # Yeni bir pozisyon açılış sinyali
        if 'Yeni' in signal and key not in open_trades:
            strategy_config = all_strategies.get(strategy_id_current, {})
            strategy_params = strategy_config.get('strategy_params', {})
            open_trades[key] = {
                'entry_price': price,
                'position_type': 'Long' if 'LONG' in signal.upper() else 'Short',
                'position_size': 100.0,  # Pozisyonu %100 olarak başlat
                'tp1_size_pct': strategy_params.get('tp1_size_pct', 50.0),
                'tp2_size_pct': strategy_params.get('tp2_size_pct', 50.0)
            }

        # Pozisyon kapatma sinyali
        elif ('Kapatıldı' in signal or 'Stop-Loss' in signal or 'Karşıt Sinyal' in signal) and key in open_trades:
            trade_info = open_trades[key]
            entry_price = trade_info['entry_price']
            position_type = trade_info['position_type']

            pnl = ((price - entry_price) / entry_price) * 100 if position_type == 'Long' else ((entry_price - price) / entry_price) * 100

            size_closed = 0
            if 'Take-Profit 1' in signal:
                size_closed = trade_info['tp1_size_pct']
            elif 'Take-Profit 2' in signal:
                size_closed = trade_info['position_size'] # Kalan pozisyonun tamamı
            else: # Stop-Loss, Karşıt Sinyal veya Manuel kapatma
                size_closed = trade_info['position_size'] # Kalan pozisyonun tamamı

            # Her bir kapalı parçayı, kendi büyüklüğüyle ağırlıklandırarak kaydet
            trades.append({'pnl': pnl, 'size': size_closed})

            # Kalan pozisyon büyüklüğünü güncelle
            trade_info['position_size'] -= size_closed

            # Eğer pozisyon tamamen kapandıysa open_trades'ten sil
            if trade_info['position_size'] <= 0.1:
                del open_trades[key]

    if not trades:
        return default_metrics

    # --- Metrik Hesaplama (Ağırlıklı Ortalama) ---
    total_pnl = sum(t['pnl'] * (t['size'] / 100.0) for t in trades)

    # Profit Factor ve diğer metrikler için her bir işlemi ayrı saymak daha doğru
    # Bu yüzden backtest'teki gibi her parçayı ayrı bir işlem gibi ele alalım
    pnl_list = [t['pnl'] for t in trades]
    total_trades_count = len(pnl_list)
    winning_trades = [p for p in pnl_list if p > 0]
    losing_trades = [p for p in pnl_list if p <= 0]

    win_rate = (len(winning_trades) / total_trades_count) * 100 if total_trades_count > 0 else 0
    avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = abs(sum(losing_trades) / len(losing_trades)) if losing_trades else 0

    gross_profit = sum(winning_trades)
    gross_loss = abs(sum(losing_trades))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf

    return {
        "Toplam İşlem": total_trades_count,
        "Başarı Oranı (%)": round(win_rate, 2),
        "Toplam Getiri (%)": round(total_pnl, 2), # Ağırlıklı toplam getiri
        "Ortalama Kazanç (%)": round(avg_win, 2),
        "Ortalama Kayıp (%)": round(avg_loss, 2),
        "Profit Factor": round(profit_factor, 2)
    }