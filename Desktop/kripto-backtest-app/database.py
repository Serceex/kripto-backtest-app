# database.py (MySQL Uyumlu)

import mysql.connector
from mysql.connector import pooling
import pandas as pd
import json
import os
from datetime import datetime
import numpy as np
import toml
import io
import time
import streamlit as st
from typing import Optional, Dict, List, Any

# MySQL bağlantı havuzu
_connection_pool = None

def get_mysql_config():
    """MySQL yapılandırmasını döndürür."""
    try:
        import streamlit as st
        mysql_config = st.secrets["mysql"]
        return {
            'host': mysql_config.get("host", "localhost"),
            'port': int(mysql_config.get("port", 3306)),
            'database': mysql_config.get("database", "kripto_backtest"),
            'user': mysql_config.get("user", "root"),
            'password': mysql_config.get("password", "")
        }
    except:
        # .streamlit/secrets.toml dosyasından oku
        script_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(script_dir, '.streamlit', 'secrets.toml')
        try:
            with open(secrets_path, 'r', encoding='utf-8') as f:
                secrets = toml.load(f)
            mysql_config = secrets.get("mysql", {})
            return {
                'host': mysql_config.get("host", "localhost"),
                'port': int(mysql_config.get("port", 3306)),
                'database': mysql_config.get("database", "kripto_backtest"),
                'user': mysql_config.get("user", "root"),
                'password': mysql_config.get("password", "")
            }
        except Exception as e:
            print(f"--- [HATA] MySQL yapılandırması okunamadı: {e} ---")
            return {
                'host': 'localhost',
                'port': 3306,
                'database': 'kripto_backtest',
                'user': 'root',
                'password': '619619'
            }

def initialize_mysql():
    """MySQL bağlantı havuzunu başlatır."""
    global _connection_pool
    
    if _connection_pool is not None:
        return _connection_pool
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            config = get_mysql_config()
            
            # Önce veritabanının var olup olmadığını kontrol et
            temp_conn = mysql.connector.connect(
                host=config['host'],
                port=config['port'],
                user=config['user'],
                password=config['password']
            )
            cursor = temp_conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {config['database']} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
            cursor.close()
            temp_conn.close()
            
            # Bağlantı havuzunu oluştur
            _connection_pool = pooling.MySQLConnectionPool(
                pool_name="kripto_pool",
                pool_size=5,
                pool_reset_session=True,
                host=config['host'],
                port=config['port'],
                database=config['database'],
                user=config['user'],
                password=config['password'],
                charset='utf8mb4',
                collation='utf8mb4_unicode_ci',
                autocommit=True
            )
            
            print("--- [DEBUG] MySQL bağlantı havuzu başarıyla oluşturuldu.")
            return _connection_pool
            
        except Exception as e:
            retry_count += 1
            if retry_count < max_retries:
                print(f"--- [UYARI] MySQL bağlantı denemesi {retry_count}/{max_retries} başarısız, yeniden deneniyor... ---")
                print(f"--- [HATA DETAYI] {e} ---")
                time.sleep(1)
            else:
                import traceback
                error_details = traceback.format_exc()
                print(f"--- [KRİTİK HATA] MySQL bağlantısı kurulamadı: {e} ---")
                print(f"--- [DETAYLI HATA] {error_details} ---")
                try:
                    st.error(f"MYSQL BAĞLANTI HATASI: {e}")
                    st.info("Lütfen .streamlit/secrets.toml dosyanızdaki MySQL yapılandırmasını kontrol edin.")
                    with st.expander("🔍 Detaylı Hata Bilgisi"):
                        st.code(error_details)
                except:
                    pass
                return None
    
    return None

def get_connection():
    """Bağlantı havuzundan bir bağlantı alır."""
    pool = initialize_mysql()
    if pool is None:
        return None
    try:
        return pool.get_connection()
    except Exception as e:
        print(f"--- [HATA] MySQL bağlantısı alınamadı: {e} ---")
        return None

def initialize_db():
    """Veritabanı tablolarını oluşturur."""
    print("--- [DEBUG] initialize_db fonksiyonu çağrıldı.")
    
    conn = get_connection()
    if conn is None:
        raise Exception("MySQL bağlantısı kurulamadı.")
    
    try:
        cursor = conn.cursor()
        
        # strategies tablosu
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategies (
                id VARCHAR(100) PRIMARY KEY,
                name VARCHAR(255),
                status VARCHAR(50) DEFAULT 'running',
                symbols JSON,
                `interval` VARCHAR(20),
                strategy_params JSON,
                orchestrator_status VARCHAR(50) DEFAULT 'active',
                is_trading_enabled BOOLEAN DEFAULT FALSE,
                rl_model_id INT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        # positions tablosu
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id VARCHAR(200) PRIMARY KEY,
                strategy_id VARCHAR(100),
                symbol VARCHAR(50),
                position VARCHAR(20),
                entry_price DECIMAL(20, 8) DEFAULT 0,
                stop_loss_price DECIMAL(20, 8) DEFAULT 0,
                tp1_price DECIMAL(20, 8) DEFAULT 0,
                tp2_price DECIMAL(20, 8) DEFAULT 0,
                tp1_hit BOOLEAN DEFAULT FALSE,
                tp2_hit BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_strategy_id (strategy_id),
                INDEX idx_symbol (symbol)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        # alarms tablosu
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alarms (
                id INT AUTO_INCREMENT PRIMARY KEY,
                strategy_id VARCHAR(100),
                `timestamp` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                symbol VARCHAR(50),
                `signal` VARCHAR(500),
                price DECIMAL(20, 8),
                INDEX idx_strategy_id (strategy_id),
                INDEX idx_timestamp (`timestamp`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        # manual_actions tablosu
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS manual_actions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                strategy_id VARCHAR(100),
                symbol VARCHAR(50),
                action VARCHAR(100),
                `timestamp` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(50) DEFAULT 'pending',
                INDEX idx_strategy_id (strategy_id),
                INDEX idx_status (status)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        # rl_models tablosu
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rl_models (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) UNIQUE,
                description TEXT,
                model_data LONGBLOB,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
        
        conn.commit()
        print("--- [DATABASE] MySQL tabloları başarıyla oluşturuldu/doğrulandı. ---")
        
    except Exception as e:
        print(f"--- [KRİTİK HATA] Tablolar oluşturulamadı: {e} ---")
        raise
    finally:
        cursor.close()
        conn.close()

def save_rl_model(name, description, model_buffer):
    """Eğitilmiş bir RL modelini veritabanına kaydeder."""
    conn = get_connection()
    if conn is None:
        raise Exception("MySQL bağlantısı yok.")
    
    try:
        cursor = conn.cursor()
        model_buffer.seek(0)
        model_data = model_buffer.read()
        
        cursor.execute("""
            INSERT INTO rl_models (name, description, model_data)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
            description = VALUES(description),
            model_data = VALUES(model_data),
            created_at = CURRENT_TIMESTAMP
        """, (name, description, model_data))
        
        conn.commit()
        print(f"--- [DATABASE] RL Modeli '{name}' başarıyla kaydedildi. ---")
        
    except Exception as e:
        print(f"--- [HATA] RL Modeli kaydedilemedi: {e} ---")
        raise
    finally:
        cursor.close()
        conn.close()

def get_rl_model_by_id(model_id):
    """Bir RL modelini ID'sine göre veritabanından çeker."""
    conn = get_connection()
    if conn is None:
        return None
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Önce ID ile dene
        cursor.execute("SELECT model_data FROM rl_models WHERE id = %s", (model_id,))
        result = cursor.fetchone()
        
        if not result:
            # Name ile dene
            cursor.execute("SELECT model_data FROM rl_models WHERE name = %s", (str(model_id),))
            result = cursor.fetchone()
        
        if result and result['model_data']:
            model_buffer = io.BytesIO(result['model_data'])
            return model_buffer
        
        return None
        
    except Exception as e:
        print(f"--- [HATA] RL Modeli alınamadı: {e} ---")
        return None
    finally:
        cursor.close()
        conn.close()

@st.cache_data(ttl=15)
def get_all_rl_models_info():
    """Tüm RL modellerinin bilgilerini listeler."""
    conn = get_connection()
    if conn is None:
        return []
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id, name, description, created_at
            FROM rl_models
            ORDER BY created_at DESC
        """)
        
        results = cursor.fetchall()
        return [
            {
                'id': row['id'],
                'name': row['name'],
                'description': row['description'] or '',
                'created_at': row['created_at']
            }
            for row in results
        ]
        
    except Exception as e:
        print(f"--- [HATA] RL Modelleri listelenemedi: {e} ---")
        return []
    finally:
        cursor.close()
        conn.close()

def add_or_update_strategy(strategy_config):
    """Bir stratejiyi ekler veya günceller."""
    conn = get_connection()
    if conn is None:
        raise Exception("MySQL bağlantısı yok.")
    
    try:
        cursor = conn.cursor(dictionary=True)
        strategy_id = strategy_config.get('id')
        new_symbols = set(strategy_config.get("symbols", []))
        
        # Mevcut stratejiyi kontrol et
        cursor.execute("SELECT symbols FROM strategies WHERE id = %s", (strategy_id,))
        existing = cursor.fetchone()
        
        if existing:
            current_symbols_json = existing.get('symbols')
            if current_symbols_json:
                if isinstance(current_symbols_json, str):
                    current_symbols = set(json.loads(current_symbols_json))
                else:
                    current_symbols = set(current_symbols_json)
            else:
                current_symbols = set()
            
            removed_symbols = current_symbols - new_symbols
            
            if removed_symbols:
                print(f"--- [DATABASE] Temizlik: Strateji '{strategy_id}' için kaldırılan semboller: {removed_symbols}")
                for symbol_to_remove in removed_symbols:
                    cursor.execute(
                        "DELETE FROM positions WHERE strategy_id = %s AND symbol = %s",
                        (strategy_id, symbol_to_remove)
                    )
                print(f"--- [DATABASE] '{strategy_id}' için eski pozisyon kayıtları temizlendi.")
        
        # RL model ID'sini kontrol et
        rl_model_id = strategy_config.get('rl_model_id')
        if rl_model_id is not None:
            try:
                rl_model_id = int(rl_model_id)
            except (ValueError, TypeError):
                rl_model_id = None
        
        # Stratejiyi ekle veya güncelle
        cursor.execute("""
            INSERT INTO strategies (id, name, status, symbols, `interval`, strategy_params, orchestrator_status, is_trading_enabled, rl_model_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            status = VALUES(status),
            symbols = VALUES(symbols),
            `interval` = VALUES(`interval`),
            strategy_params = VALUES(strategy_params),
            orchestrator_status = VALUES(orchestrator_status),
            is_trading_enabled = VALUES(is_trading_enabled),
            rl_model_id = VALUES(rl_model_id)
        """, (
            strategy_id,
            strategy_config.get('name'),
            strategy_config.get('status', 'running'),
            json.dumps(list(new_symbols)),
            strategy_config.get('interval'),
            json.dumps(strategy_config.get('strategy_params', {})),
            strategy_config.get('orchestrator_status', 'active'),
            strategy_config.get('is_trading_enabled', False),
            rl_model_id
        ))
        
        conn.commit()
        print(f"--- [DATABASE] Strateji '{strategy_id}' başarıyla kaydedildi/güncellendi. ---")
        
    except Exception as e:
        print(f"--- [HATA] Strateji kaydedilemedi: {e} ---")
        raise
    finally:
        cursor.close()
        conn.close()

def remove_strategy(strategy_id):
    """Bir stratejiyi ve ilişkili verileri siler."""
    conn = get_connection()
    if conn is None:
        raise Exception("MySQL bağlantısı yok.")
    
    try:
        cursor = conn.cursor()
        
        # İlişkili verileri sil
        cursor.execute("DELETE FROM positions WHERE strategy_id = %s", (strategy_id,))
        cursor.execute("DELETE FROM alarms WHERE strategy_id = %s", (strategy_id,))
        cursor.execute("DELETE FROM manual_actions WHERE strategy_id = %s", (strategy_id,))
        
        # Ana strateji kaydını sil
        cursor.execute("DELETE FROM strategies WHERE id = %s", (strategy_id,))
        
        conn.commit()
        print(f"--- [DATABASE] Strateji (ID: {strategy_id}) ve tüm ilişkili verileri silindi. ---")
        
    except Exception as e:
        print(f"--- [HATA] Strateji silinemedi: {e} ---")
        raise
    finally:
        cursor.close()
        conn.close()

@st.cache_data(ttl=15)
def get_all_strategies():
    """Tüm stratejileri döndürür."""
    conn = get_connection()
    if conn is None:
        return []
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM strategies")
        
        results = []
        for row in cursor.fetchall():
            strategy = dict(row)
            # JSON alanlarını parse et
            if strategy.get('symbols'):
                if isinstance(strategy['symbols'], str):
                    strategy['symbols'] = json.loads(strategy['symbols'])
            else:
                strategy['symbols'] = []
            
            if strategy.get('strategy_params'):
                if isinstance(strategy['strategy_params'], str):
                    strategy['strategy_params'] = json.loads(strategy['strategy_params'])
            else:
                strategy['strategy_params'] = {}
            
            results.append(strategy)
        
        return results
        
    except Exception as e:
        print(f"--- [HATA] Stratejiler alınamadı: {e} ---")
        return []
    finally:
        cursor.close()
        conn.close()

def update_position(strategy_id, symbol, position, entry_price, sl_price=0, tp1_price=0, tp2_price=0, tp1_hit=False, tp2_hit=False):
    """Bir pozisyonu ekler veya günceller."""
    conn = get_connection()
    if conn is None:
        print("--- [UYARI] MySQL bağlantısı yok, pozisyon güncellenemedi. ---")
        return
    
    try:
        cursor = conn.cursor()
        position_id = f"{strategy_id}_{symbol}"
        
        cursor.execute("""
            INSERT INTO positions (id, strategy_id, symbol, position, entry_price, stop_loss_price, tp1_price, tp2_price, tp1_hit, tp2_hit)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            position = VALUES(position),
            entry_price = VALUES(entry_price),
            stop_loss_price = VALUES(stop_loss_price),
            tp1_price = VALUES(tp1_price),
            tp2_price = VALUES(tp2_price),
            tp1_hit = VALUES(tp1_hit),
            tp2_hit = VALUES(tp2_hit)
        """, (position_id, strategy_id, symbol, position, entry_price, sl_price, tp1_price, tp2_price, tp1_hit, tp2_hit))
        
        conn.commit()
        
    except Exception as e:
        print(f"--- [HATA] Pozisyon güncellenemedi: {e} ---")
        raise
    finally:
        cursor.close()
        conn.close()

def get_positions_for_strategy(strategy_id):
    """Bir strateji için tüm pozisyonları döndürür."""
    conn = get_connection()
    if conn is None:
        return {}
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM positions WHERE strategy_id = %s", (strategy_id,))
        
        positions = {}
        for row in cursor.fetchall():
            positions[row['symbol']] = {
                'strategy_id': row['strategy_id'],
                'symbol': row['symbol'],
                'position': row['position'],
                'entry_price': float(row['entry_price']) if row['entry_price'] else 0,
                'stop_loss_price': float(row['stop_loss_price']) if row['stop_loss_price'] else 0,
                'tp1_price': float(row['tp1_price']) if row['tp1_price'] else 0,
                'tp2_price': float(row['tp2_price']) if row['tp2_price'] else 0,
                'tp1_hit': bool(row['tp1_hit']),
                'tp2_hit': bool(row['tp2_hit'])
            }
        
        return positions
        
    except Exception as e:
        print(f"--- [HATA] Pozisyonlar alınamadı: {e} ---")
        return {}
    finally:
        cursor.close()
        conn.close()

def log_alarm_db(strategy_id, symbol, signal, price):
    """Bir alarm/sinyal kaydı oluşturur."""
    conn = get_connection()
    if conn is None:
        print("--- [UYARI] MySQL bağlantısı yok, alarm kaydedilemedi. ---")
        return
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO alarms (strategy_id, symbol, `signal`, price)
            VALUES (%s, %s, %s, %s)
        """, (strategy_id, symbol, signal, price))
        
        conn.commit()
        
    except Exception as e:
        print(f"--- [HATA] Alarm kaydedilemedi: {e} ---")
    finally:
        cursor.close()
        conn.close()

@st.cache_data(ttl=60)
def get_alarm_history_db(limit=50):
    """Alarm geçmişini döndürür."""
    conn = get_connection()
    if conn is None:
        return pd.DataFrame(columns=['Zaman', 'Sembol', 'Sinyal', 'Fiyat'])
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT `timestamp`, symbol, `signal`, price
            FROM alarms
            ORDER BY `timestamp` DESC
            LIMIT %s
        """, (limit,))
        
        results = cursor.fetchall()
        
        if results:
            df = pd.DataFrame(results)
            df.columns = ['Zaman', 'Sembol', 'Sinyal', 'Fiyat']
            return df
        
        return pd.DataFrame(columns=['Zaman', 'Sembol', 'Sinyal', 'Fiyat'])
        
    except Exception as e:
        print(f"--- [HATA] Alarm geçmişi alınamadı: {e} ---")
        return pd.DataFrame(columns=['Zaman', 'Sembol', 'Sinyal', 'Fiyat'])
    finally:
        cursor.close()
        conn.close()

@st.cache_data(ttl=15)
def get_all_open_positions():
    """Tüm açık pozisyonları döndürür."""
    conn = get_connection()
    if conn is None:
        return pd.DataFrame()
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.*, s.name as strategy_name
            FROM positions p
            LEFT JOIN strategies s ON p.strategy_id = s.id
            WHERE p.position IS NOT NULL AND p.position != ''
        """)
        
        results = cursor.fetchall()
        
        if results:
            positions = []
            for row in results:
                if row['position']:
                    positions.append({
                        'strategy_id': row['strategy_id'],
                        'Strateji Adı': row['strategy_name'] or '',
                        'Sembol': row['symbol'],
                        'Pozisyon': row['position'],
                        'Giriş Fiyatı': float(row['entry_price']) if row['entry_price'] else 0,
                        'Stop Loss': float(row['stop_loss_price']) if row['stop_loss_price'] else 0,
                        'TP1': float(row['tp1_price']) if row['tp1_price'] else 0,
                        'TP2': float(row['tp2_price']) if row['tp2_price'] else 0
                    })
            
            return pd.DataFrame(positions) if positions else pd.DataFrame()
        
        return pd.DataFrame()
        
    except Exception as e:
        print(f"--- [HATA] Açık pozisyonlar alınamadı: {e} ---")
        return pd.DataFrame()
    finally:
        cursor.close()
        conn.close()

def update_strategy_status(strategy_id, status, is_orchestrator_decision=False):
    """Bir stratejinin durumunu günceller."""
    conn = get_connection()
    if conn is None:
        print("--- [UYARI] MySQL bağlantısı yok, strateji durumu güncellenemedi. ---")
        return
    
    try:
        cursor = conn.cursor()
        
        if is_orchestrator_decision:
            cursor.execute("UPDATE strategies SET orchestrator_status = %s WHERE id = %s", (status, strategy_id))
        else:
            cursor.execute("UPDATE strategies SET status = %s WHERE id = %s", (status, strategy_id))
        
        conn.commit()
        
    except Exception as e:
        print(f"--- [HATA] Strateji durumu güncellenemedi: {e} ---")
        raise
    finally:
        cursor.close()
        conn.close()

def issue_manual_action(strategy_id, symbol, action):
    """Manuel bir işlem kaydı oluşturur."""
    conn = get_connection()
    if conn is None:
        print("--- [UYARI] MySQL bağlantısı yok, manuel işlem kaydedilemedi. ---")
        return
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO manual_actions (strategy_id, symbol, action)
            VALUES (%s, %s, %s)
        """, (strategy_id, symbol, action))
        
        conn.commit()
        
    except Exception as e:
        print(f"--- [HATA] Manuel işlem kaydedilemedi: {e} ---")
        raise
    finally:
        cursor.close()
        conn.close()

def get_and_clear_pending_actions(strategy_id):
    """Bekleyen manuel işlemleri alır ve tamamlandı olarak işaretler."""
    conn = get_connection()
    if conn is None:
        return []
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Bekleyen işlemleri al
        cursor.execute("""
            SELECT id, symbol, action
            FROM manual_actions
            WHERE strategy_id = %s AND status = 'pending'
        """, (strategy_id,))
        
        results = cursor.fetchall()
        actions = []
        
        for row in results:
            actions.append({
                'id': row['id'],
                'symbol': row['symbol'],
                'action': row['action']
            })
            # Durumu güncelle
            cursor.execute("UPDATE manual_actions SET status = 'completed' WHERE id = %s", (row['id'],))
        
        conn.commit()
        return actions
        
    except Exception as e:
        print(f"--- [HATA] Bekleyen işlemler alınamadı: {e} ---")
        return []
    finally:
        cursor.close()
        conn.close()

@st.cache_data(ttl=30)
def get_live_closed_trades_metrics(strategy_id=None):
    """Canlı kapanan işlemlerin metriklerini hesaplar."""
    default_metrics = {
        "Toplam İşlem": 0, "Başarı Oranı (%)": 0.0, "Toplam Getiri (%)": 0.0,
        "Ortalama Kazanç (%)": 0.0, "Ortalama Kayıp (%)": 0.0, "Profit Factor": 0.0
    }
    
    conn = get_connection()
    if conn is None:
        return default_metrics
    
    try:
        cursor = conn.cursor(dictionary=True)
        
        # Tüm stratejileri al
        all_strategies = {s['id']: s for s in get_all_strategies()}
        
        # Alarmları al
        if strategy_id:
            cursor.execute("""
                SELECT strategy_id, symbol, `signal`, price, `timestamp`
                FROM alarms
                WHERE strategy_id = %s
                ORDER BY `timestamp` ASC
            """, (strategy_id,))
        else:
            cursor.execute("""
                SELECT strategy_id, symbol, `signal`, price, `timestamp`
                FROM alarms
                ORDER BY `timestamp` ASC
            """)
        
        alarms = []
        for row in cursor.fetchall():
            signal = row.get('signal', '')
            if any(keyword in signal for keyword in ['Yeni', 'Kapatıldı', 'Stop-Loss', 'Karşıt Sinyal']):
                alarms.append({
                    'strategy_id': row['strategy_id'],
                    'symbol': row['symbol'],
                    'signal': signal,
                    'price': float(row['price']) if row['price'] else 0,
                    'timestamp': row['timestamp']
                })
        
        if not alarms:
            return default_metrics
        
        # İşlemleri hesapla
        trades = []
        open_trades = {}
        
        for alarm in alarms:
            key = (alarm['strategy_id'], alarm['symbol'])
            signal = alarm['signal']
            price = alarm['price']
            strategy_id_current = alarm['strategy_id']
            
            if 'Yeni' in signal and key not in open_trades:
                strategy_config = all_strategies.get(strategy_id_current, {})
                strategy_params = strategy_config.get('strategy_params', {})
                open_trades[key] = {
                    'entry_price': price,
                    'position_type': 'Long' if 'LONG' in signal.upper() else 'Short',
                    'position_size': 100.0,
                    'tp1_size_pct': strategy_params.get('tp1_size_pct', 50.0),
                    'tp2_size_pct': strategy_params.get('tp2_size_pct', 50.0)
                }
            elif ('Kapatıldı' in signal or 'Stop-Loss' in signal or 'Karşıt Sinyal' in signal) and key in open_trades:
                trade_info = open_trades[key]
                entry_price = trade_info['entry_price']
                position_type = trade_info['position_type']
                
                pnl = ((price - entry_price) / entry_price) * 100 if position_type == 'Long' else ((entry_price - price) / entry_price) * 100
                
                size_closed = 0
                if 'Take-Profit 1' in signal:
                    size_closed = trade_info['tp1_size_pct']
                elif 'Take-Profit 2' in signal:
                    size_closed = trade_info['position_size']
                else:
                    size_closed = trade_info['position_size']
                
                trades.append({'pnl': pnl, 'size': size_closed})
                trade_info['position_size'] -= size_closed
                
                if trade_info['position_size'] <= 0.1:
                    del open_trades[key]
        
        if not trades:
            return default_metrics
        
        total_pnl = sum(t['pnl'] * (t['size'] / 100.0) for t in trades)
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
            "Toplam Getiri (%)": round(total_pnl, 2),
            "Ortalama Kazanç (%)": round(avg_win, 2),
            "Ortalama Kayıp (%)": round(avg_loss, 2),
            "Profit Factor": round(profit_factor, 2)
        }
        
    except Exception as e:
        print(f"--- [HATA] Metrikler hesaplanamadı: {e} ---")
        return default_metrics
    finally:
        cursor.close()
        conn.close()

def remove_rl_model_by_id(model_id):
    """Veritabanından bir RL modelini ID'sine göre siler."""
    conn = get_connection()
    if conn is None:
        raise Exception("MySQL bağlantısı yok.")
    
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM rl_models WHERE id = %s OR name = %s", (model_id, str(model_id)))
        conn.commit()
        print(f"--- [DATABASE] RL Modeli (ID: {model_id}) başarıyla silindi. ---")
        
    except Exception as e:
        print(f"--- [HATA] RL Modeli silinemedi: {e} ---")
        raise
    finally:
        cursor.close()
        conn.close()
