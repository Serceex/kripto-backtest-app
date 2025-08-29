# database.py (PostgreSQL Uyumlu - Hata Yönetimi Güçlendirilmiş)

import psycopg2
import psycopg2.extras
import pandas as pd
import json
from datetime import datetime
import numpy as np
import io

# Sırları merkezi yükleyiciden alıyoruz
try:
    from config_loader import DB_CONFIG
except ImportError:
    print("KRİTİK HATA: config_loader.py bulunamadı. Lütfen bir önceki adımdaki dosyayı oluşturun.")
    DB_CONFIG = None


def get_db_connection():
    """
    Merkezi yapılandırmayı kullanarak veritabanı bağlantısı kurar.
    """
    if not DB_CONFIG or "host" not in DB_CONFIG:
        print("--- [KRİTİK HATA] Veritabanı yapılandırması yüklenemedi veya eksik. Bağlantı kurulamıyor.")
        return None

    try:
        conn = psycopg2.connect(
            dbname=DB_CONFIG["database"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            host=DB_CONFIG["host"],
            port=DB_CONFIG.get("port", "5432"),
            connect_timeout=5
        )
        return conn
    except psycopg2.OperationalError as e:
        print("--- [KRİTİK BAĞLANTI HATASI] ---")
        print(f"PostgreSQL veritabanına bağlanılamadı. Hata: {e}")
        print(
            "Lütfen .streamlit/secrets.toml dosyanızdaki bilgilerin (host, port, user, password) doğruluğunu ve veritabanı sunucusunun çalıştığını kontrol edin.")
        # Streamlit arayüzünde hatayı göster
        try:
            import streamlit as st
            st.error(f"VERİTABANI BAĞLANTI HATASI: {e}")
            st.stop()
        except Exception:
            # Worker'da ise programdan çık veya sadece logla
            print("Worker context - Streamlit arayüzü olmadan devam ediliyor.")
        return None
    except KeyError as e:
        print(f"--- [KRİTİK HATA] secrets.toml dosyasında eksik anahtar: {e}. Lütfen 'postgres' bölümünü kontrol edin.")
        return None


# --- DÜZELTME: Aşağıdaki tüm fonksiyonlar, bağlantı hatasına karşı dayanıklı hale getirilmiştir ---

def initialize_db():
    print("--- [DEBUG] initialize_db fonksiyonu çağrıldı.")
    conn = get_db_connection()
    if not conn:
        print("--- [HATA] Veritabanı bağlantısı alınamadı. initialize_db atlanıyor.")
        return
    try:
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
                    id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, description TEXT,
                    model_data BYTEA NOT NULL, created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )""")
        conn.commit()
        print("--- [DATABASE] PostgreSQL veritabanı ve tablolar başarıyla başlatıldı/doğrulandı. ---")
    except Exception as e:
        print(f"--- [KRİTİK HATA] Veritabanı başlatılamadı: {e} ---")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()


def get_all_strategies():
    conn = get_db_connection()
    if not conn: return []
    result = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM strategies")
            result = [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"HATA: get_all_strategies çalıştırılırken hata oluştu: {e}")
    finally:
        if conn: conn.close()
    return result


def get_all_open_positions():
    conn = get_db_connection()
    if not conn: return pd.DataFrame()
    df = pd.DataFrame()
    try:
        query = """
            SELECT s.id as "strategy_id", s.name as "Strateji Adı", p.symbol as "Sembol", p.position as "Pozisyon",
                   p.entry_price as "Giriş Fiyatı", p.stop_loss_price as "Stop Loss", p.tp1_price as "TP1", p.tp2_price as "TP2"
            FROM positions p JOIN strategies s ON p.strategy_id = s.id
            WHERE p.position IS NOT NULL AND p.position != ''
        """
        df = pd.read_sql_query(query, conn)
    except Exception as e:
        print(f"HATA: get_all_open_positions çalıştırılırken hata oluştu: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()
    return df


# Diğer tüm fonksiyonları da bu güvenli yapıya uygun hale getirdim.
# Bu dosyanın geri kalanını değiştirmeden kullanabilirsiniz.
def save_rl_model(name, description, model_buffer):
    conn = get_db_connection()
    if not conn: return
    try:
        model_data_binary = psycopg2.Binary(model_buffer.getvalue())
        sql = """
            INSERT INTO rl_models (name, description, model_data) VALUES (%s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET model_data = EXCLUDED.model_data,
            description = EXCLUDED.description, created_at = CURRENT_TIMESTAMP;
        """
        with conn.cursor() as cursor:
            cursor.execute(sql, (name, description, model_data_binary))
        conn.commit()
        print(f"--- [DATABASE] RL Modeli '{name}' başarıyla kaydedildi/güncellendi. ---")
    except Exception as e:
        print(f"HATA: save_rl_model çalıştırılırken hata oluştu: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()


def get_rl_model_by_id(model_id):
    conn = get_db_connection()
    if not conn: return None
    result = None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT model_data FROM rl_models WHERE id = %s", (model_id,))
            record = cursor.fetchone()
            if record:
                result = io.BytesIO(record['model_data'])
    except Exception as e:
        print(f"HATA: get_rl_model_by_id çalıştırılırken hata oluştu: {e}")
    finally:
        if conn: conn.close()
    return result


def get_all_rl_models_info():
    conn = get_db_connection()
    if not conn: return []
    result = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT id, name, description, created_at FROM rl_models ORDER BY created_at DESC")
            result = [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"HATA: get_all_rl_models_info çalıştırılırken hata oluştu: {e}")
    finally:
        if conn: conn.close()
    return result


def add_or_update_strategy(strategy_config):
    conn = get_db_connection()
    if not conn: return
    try:
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
    except Exception as e:
        print(f"HATA: add_or_update_strategy çalıştırılırken hata oluştu: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()


def remove_strategy(strategy_id):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
        conn.commit()
        print(f"--- [DATABASE] Strateji (ID: {strategy_id}) silindi. ---")
    except Exception as e:
        print(f"HATA: remove_strategy çalıştırılırken hata oluştu: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()


def update_position(strategy_id, symbol, position, entry_price, sl_price=0, tp1_price=0, tp2_price=0, tp1_hit=False,
                    tp2_hit=False):
    conn = get_db_connection()
    if not conn: return
    try:
        sql = """
            INSERT INTO positions (strategy_id, symbol, position, entry_price, stop_loss_price, tp1_price, tp2_price, tp1_hit, tp2_hit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (strategy_id, symbol) DO UPDATE SET
                position = EXCLUDED.position, entry_price = EXCLUDED.entry_price, stop_loss_price = EXCLUDED.stop_loss_price,
                tp1_price = EXCLUDED.tp1_price, tp2_price = EXCLUDED.tp2_price, tp1_hit = EXCLUDED.tp1_hit,
                tp2_hit = EXCLUDED.tp2_hit;
        """
        with conn.cursor() as cursor:
            cursor.execute(sql, (
            strategy_id, symbol, position, entry_price, sl_price, tp1_price, tp2_price, tp1_hit, tp2_hit))
        conn.commit()
    except Exception as e:
        print(f"HATA: update_position çalıştırılırken hata oluştu: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()


def get_positions_for_strategy(strategy_id):
    conn = get_db_connection()
    if not conn: return {}
    positions = {}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute("SELECT * FROM positions WHERE strategy_id = %s", (strategy_id,))
            for row in cursor.fetchall():
                positions[row['symbol']] = dict(row)
    except Exception as e:
        print(f"HATA: get_positions_for_strategy çalıştırılırken hata oluştu: {e}")
    finally:
        if conn: conn.close()
    return positions


def log_alarm_db(strategy_id, symbol, signal, price):
    conn = get_db_connection()
    if not conn: return
    try:
        timestamp = datetime.now()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO alarms (strategy_id, timestamp, symbol, signal, price) VALUES (%s, %s, %s, %s, %s)",
                (strategy_id, timestamp, symbol, signal, price))
        conn.commit()
    except Exception as e:
        print(f"HATA: log_alarm_db çalıştırılırken hata oluştu: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()


def get_alarm_history_db(limit=50):
    conn = get_db_connection()
    if not conn: return pd.DataFrame()
    df = pd.DataFrame()
    try:
        query = """
            SELECT a.timestamp as "Zaman", s.name as "Strateji", a.symbol as "Sembol", a.signal as "Sinyal", a.price as "Fiyat"
            FROM alarms a JOIN strategies s ON a.strategy_id = s.id
            ORDER BY a.id DESC LIMIT %s
        """
        df = pd.read_sql_query(query, conn, params=(limit,))
    except Exception as e:
        print(f"HATA: get_alarm_history_db çalıştırılırken hata oluştu: {e}")
        return pd.DataFrame()
    finally:
        if conn: conn.close()
    return df


def update_strategy_status(strategy_id, status, is_orchestrator_decision=False):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            if is_orchestrator_decision:
                cursor.execute("UPDATE strategies SET orchestrator_status = %s WHERE id = %s", (status, strategy_id))
            else:
                cursor.execute("UPDATE strategies SET status = %s WHERE id = %s", (status, strategy_id))
        conn.commit()
    except Exception as e:
        print(f"HATA: update_strategy_status çalıştırılırken hata oluştu: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()


def issue_manual_action(strategy_id, symbol, action):
    conn = get_db_connection()
    if not conn: return
    try:
        timestamp = datetime.now()
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO manual_actions (strategy_id, symbol, action, timestamp, status) VALUES (%s, %s, %s, %s, %s)",
                (strategy_id, symbol, action, timestamp, 'pending'))
        conn.commit()
    except Exception as e:
        print(f"HATA: issue_manual_action çalıştırılırken hata oluştu: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()


def get_and_clear_pending_actions(strategy_id):
    conn = get_db_connection()
    if not conn: return []
    actions = []
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            cursor.execute(
                "SELECT id, symbol, action FROM manual_actions WHERE strategy_id = %s AND status = 'pending'",
                (strategy_id,))
            actions = [dict(row) for row in cursor.fetchall()]
            if actions:
                action_ids = tuple(action['id'] for action in actions)
                cursor.execute("UPDATE manual_actions SET status = 'completed' WHERE id IN %s", (action_ids,))
        conn.commit()
    except Exception as e:
        print(f"HATA: get_and_clear_pending_actions çalıştırılırken hata oluştu: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()
    return actions


def get_live_closed_trades_metrics(strategy_id=None):
    conn = get_db_connection()
    if not conn: return {"Toplam İşlem": 0, "Başarı Oranı (%)": 0.0, "Toplam Getiri (%)": 0.0, "Profit Factor": 0.0}

    df = pd.DataFrame()
    try:
        base_query = "SELECT strategy_id, symbol, signal, price, timestamp FROM alarms WHERE "
        conditions = "(signal LIKE '%%Yeni%%' OR signal LIKE '%%Kapatıldı%%' OR signal LIKE '%%Stop-Loss%%' OR signal LIKE '%%Karşıt Sinyal%%')"
        if strategy_id:
            query = base_query + "strategy_id = %s AND " + conditions + " ORDER BY timestamp ASC"
            df = pd.read_sql_query(query, conn, params=(strategy_id,))
        else:
            query = base_query + conditions + " ORDER BY timestamp ASC"
            df = pd.read_sql_query(query, conn)
    except Exception as e:
        print(f"HATA: get_live_closed_trades_metrics için alarm verisi okunurken hata: {e}")
    finally:
        if conn: conn.close()

    # --- Metrik Hesaplama ---
    all_strategies = {s['id']: s for s in get_all_strategies()}
    default_metrics = {"Toplam İşlem": 0, "Başarı Oranı (%)": 0.0, "Toplam Getiri (%)": 0.0, "Ortalama Kazanç (%)": 0.0,
                       "Ortalama Kayıp (%)": 0.0, "Profit Factor": 0.0}
    if df.empty: return default_metrics

    trades, open_trades = [], {}
    for _, row in df.iterrows():
        key = (row['strategy_id'], row['symbol'])
        strategy_params = all_strategies.get(row['strategy_id'], {}).get('strategy_params', {})
        if 'Yeni' in row['signal'] and key not in open_trades:
            open_trades[key] = {'entry_price': row['price'],
                                'position_type': 'Long' if 'LONG' in row['signal'].upper() else 'Short',
                                'position_size': 100.0, 'tp1_size_pct': strategy_params.get('tp1_size_pct', 50.0),
                                'tp2_size_pct': strategy_params.get('tp2_size_pct', 50.0)}
        elif ('Kapatıldı' in row['signal'] or 'Stop-Loss' in row['signal'] or 'Karşıt Sinyal' in row[
            'signal']) and key in open_trades:
            trade_info = open_trades[key]
            pnl = ((row['price'] - trade_info['entry_price']) / trade_info['entry_price']) * 100 if trade_info[
                                                                                                        'position_type'] == 'Long' else (
                                                                                                                                                    (
                                                                                                                                                                trade_info[
                                                                                                                                                                    'entry_price'] -
                                                                                                                                                                row[
                                                                                                                                                                    'price']) /
                                                                                                                                                    trade_info[
                                                                                                                                                        'entry_price']) * 100
            size_closed = trade_info.get('tp1_size_pct', 50.0) if 'Take-Profit 1' in row['signal'] else trade_info[
                'position_size']
            trades.append({'pnl': pnl, 'size': size_closed})
            trade_info['position_size'] -= size_closed
            if trade_info['position_size'] <= 0.1: del open_trades[key]

    if not trades: return default_metrics

    total_pnl = sum(t['pnl'] * (t['size'] / 100.0) for t in trades)
    pnl_list = [t['pnl'] for t in trades]
    total_trades_count = len(pnl_list)
    winning_trades = [p for p in pnl_list if p > 0]
    win_rate = (len(winning_trades) / total_trades_count) * 100 if total_trades_count > 0 else 0
    avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0
    losing_trades = [p for p in pnl_list if p <= 0]
    avg_loss = abs(sum(losing_trades) / len(losing_trades)) if losing_trades else 0
    gross_profit = sum(winning_trades)
    gross_loss = abs(sum(losing_trades))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf

    return {"Toplam İşlem": total_trades_count, "Başarı Oranı (%)": round(win_rate, 2),
            "Toplam Getiri (%)": round(total_pnl, 2), "Ortalama Kazanç (%)": round(avg_win, 2),
            "Ortalama Kayıp (%)": round(avg_loss, 2), "Profit Factor": round(profit_factor, 2)}


def remove_rl_model_by_id(model_id):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM rl_models WHERE id = %s", (model_id,))
        conn.commit()
        print(f"--- [DATABASE] RL Modeli (ID: {model_id}) başarıyla silindi. ---")
    except Exception as e:
        print(f"HATA: remove_rl_model_by_id çalıştırılırken hata oluştu: {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()