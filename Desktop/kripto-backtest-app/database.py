# database.py dosyasının yeni, TAM ve DOĞRU içeriği

import sqlite3
import pandas as pd
import json
import threading
import os
from datetime import datetime
import numpy as np  # Numpy'ı import ediyoruz

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

            # --- ORKESTRATÖR GÜNCELLEMESİ ---
            # Tabloya 'orchestrator_status' sütununu ekle (eğer yoksa)
            try:
                cursor.execute("ALTER TABLE strategies ADD COLUMN orchestrator_status TEXT DEFAULT 'active'")
                conn.commit()
                print("--- [DATABASE] 'strategies' tablosuna 'orchestrator_status' sütunu eklendi. ---")
            except sqlite3.OperationalError:
                # Sütun zaten varsa bu hata alınır, sorun değil.
                pass
            # --- GÜNCELLEME SONU ---

            cursor.execute("""
              CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                name TEXT,
                status TEXT DEFAULT 'running',
                symbols TEXT,
                interval TEXT,
                strategy_params TEXT,
                orchestrator_status TEXT DEFAULT 'active' -- Bu satırın varlığından emin oluyoruz
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
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT,
                timestamp TEXT,
                symbol TEXT,
                signal TEXT,
                price REAL,
                FOREIGN KEY (strategy_id) REFERENCES strategies (id) ON DELETE CASCADE
            )""")
            cursor.execute("""
                        CREATE TABLE IF NOT EXISTS manual_actions (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            strategy_id TEXT NOT NULL,
                            symbol TEXT NOT NULL,
                            action TEXT NOT NULL, -- e.g., 'CLOSE_POSITION'
                            timestamp TEXT NOT NULL,
                            status TEXT DEFAULT 'pending' -- pending, completed
                        )""")
            conn.commit()
    print("--- [DATABASE] Veritabanı başlatıldı. ---")


# ... (dosyanın geri kalanı aynı kalacak) ...
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
                    INSERT INTO strategies (id, name, status, symbols, interval, strategy_params, orchestrator_status)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name, status=excluded.status, symbols=excluded.symbols,
                        interval=excluded.interval, strategy_params=excluded.strategy_params,
                        orchestrator_status=excluded.orchestrator_status
                """, (
                    strategy_config.get('id'), strategy_config.get('name'),
                    strategy_config.get('status', 'running'), symbols_json,
                    strategy_config.get('interval'), params_json,
                    strategy_config.get('orchestrator_status', 'active')  # Yeni alanı ekledik
                ))
                conn.commit()
                print("[YAZMA - Adım 3] Veritabanına yazma BAŞARILI.")
        except Exception as e:
            print(f"[YAZMA - HATA] SQL sorgusunda hata: {e}")


# ... (dosyanın geri kalanı aynı kalacak, diğer fonksiyonlar değişmeyecek) ...

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
            positions = conn.execute("SELECT symbol, position, entry_price FROM positions WHERE strategy_id = ?",
                                     (strategy_id,)).fetchall()
            return {p['symbol']: {'position': p['position'], 'entry_price': p['entry_price']} for p in positions}


def log_alarm_db(strategy_id, symbol, signal, price):
    """Bir alarmı, ilişkili olduğu strateji ID'si ile birlikte veritabanına kaydeder."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        with get_db_connection() as conn:
            conn.execute("INSERT INTO alarms (strategy_id, timestamp, symbol, signal, price) VALUES (?, ?, ?, ?, ?)",
                         (strategy_id, timestamp, symbol, signal, price))
            conn.commit()
    print(f"--- [DATABASE] Alarm loglandı: Strateji({strategy_id}) - {symbol} - {signal} ---")


def get_alarm_history_db(limit=50):
    """Sadece veritabanında MEVCUT olan stratejilerden gelen son alarmları döndürür."""
    with db_lock:
        with get_db_connection() as conn:
            query = """
                SELECT a.timestamp as Zaman, a.symbol as Sembol, a.signal as Sinyal, a.price as Fiyat
                FROM alarms a
                JOIN strategies s ON a.strategy_id = s.id
                ORDER BY a.id DESC
                LIMIT ?
            """
            df = pd.read_sql_query(query, conn, params=(limit,))
            return df


def get_all_open_positions():
    """Tüm stratejilerdeki mevcut açık pozisyonları bir DataFrame olarak döndürür."""
    with db_lock:
        with get_db_connection() as conn:
            query = """
                SELECT
                    s.id as "strategy_id",
                    s.name as "Strateji Adı",
                    p.symbol as "Sembol",
                    p.position as "Pozisyon",
                    p.entry_price as "Giriş Fiyatı"
                FROM positions p
                JOIN strategies s ON p.strategy_id = s.id
                WHERE p.position IS NOT NULL AND p.position != ''
            """
            df = pd.read_sql_query(query, conn)
            return df


def get_live_closed_trades_metrics(strategy_id=None):
    """
    Canlıda kapanan işlemlerin detaylı metriklerini hesaplar.
    Eğer strategy_id verilirse, sadece o strateji için hesaplar.
    """
    default_metrics = {
        "Toplam İşlem": 0, "Başarı Oranı (%)": 0.0, "Toplam Getiri (%)": 0.0,
        "Ortalama Kazanç (%)": 0.0, "Ortalama Kayıp (%)": 0.0, "Profit Factor": 0.0
    }

    with db_lock:
        with get_db_connection() as conn:
            query = "SELECT strategy_id, symbol, signal, price, timestamp FROM alarms WHERE signal LIKE '%Pozisyon%' ORDER BY timestamp ASC"
            params = ()
            if strategy_id:
                query = "SELECT strategy_id, symbol, signal, price, timestamp FROM alarms WHERE strategy_id = ? AND signal LIKE '%Pozisyon%' ORDER BY timestamp ASC"
                params = (strategy_id,)
            df = pd.read_sql_query(query, conn, params=params)

    if df.empty:
        return default_metrics

    trades = []
    open_trades = {}

    for _, row in df.iterrows():
        key = (row['strategy_id'], row['symbol'])
        signal = row['signal']
        price = row['price']

        if 'Yeni' in signal and key not in open_trades:
            open_trades[key] = {'entry_price': price, 'position_type': 'Long' if 'LONG' in signal else 'Short'}
        elif ('Kapatıldı' in signal or 'Stop-Loss' in signal) and key in open_trades:
            entry_price = open_trades[key]['entry_price']
            position_type = open_trades[key]['position_type']
            pnl = ((price - entry_price) / entry_price) * 100 if position_type == 'Long' else ((
                                                                                                           entry_price - price) / entry_price) * 100
            trades.append({'pnl': pnl})
            del open_trades[key]

    if not trades:
        return default_metrics

    pnl_list = [t['pnl'] for t in trades]
    total_trades = len(pnl_list)
    winning_trades = [p for p in pnl_list if p > 0]
    losing_trades = [p for p in pnl_list if p <= 0]

    win_rate = (len(winning_trades) / total_trades) * 100 if total_trades > 0 else 0
    total_pnl = sum(pnl_list)
    avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss = abs(sum(losing_trades) / len(losing_trades)) if losing_trades else 0
    profit_factor = sum(winning_trades) / abs(sum(losing_trades)) if losing_trades and sum(
        losing_trades) != 0 else np.inf

    return {
        "Toplam İşlem": total_trades,
        "Başarı Oranı (%)": round(win_rate, 2),
        "Toplam Getiri (%)": round(total_pnl, 2),
        "Ortalama Kazanç (%)": round(avg_win, 2),
        "Ortalama Kayıp (%)": round(avg_loss, 2),
        "Profit Factor": round(profit_factor, 2)
    }


def update_strategy_status(strategy_id, status, is_orchestrator_decision=False):
    """
    Bir stratejinin durumunu günceller.
    'status' -> kullanıcı tarafından (running, paused)
    'orchestrator_status' -> Orkestratör tarafından (active, inactive)
    """
    with db_lock:
        with get_db_connection() as conn:
            if is_orchestrator_decision:
                conn.execute("UPDATE strategies SET orchestrator_status = ? WHERE id = ?", (status, strategy_id))
                print(f"--- [DATABASE] Orkestratör kararı: Strateji {strategy_id} durumu -> {status} ---")
            else:
                conn.execute("UPDATE strategies SET status = ? WHERE id = ?", (status, strategy_id))
                print(f"--- [DATABASE] Strateji {strategy_id} durumu güncellendi: {status} ---")
            conn.commit()


def issue_manual_action(strategy_id, symbol, action):
    """Arayüzden çalışana manuel bir komut gönderir."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db_lock:
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO manual_actions (strategy_id, symbol, action, timestamp) VALUES (?, ?, ?, ?)",
                (strategy_id, symbol, action, timestamp)
            )
            conn.commit()
    print(f"--- [MANUAL ACTION] Issued: {action} for {symbol} on strategy {strategy_id} ---")


def get_and_clear_pending_actions(strategy_id):
    """Belirli bir strateji için bekleyen komutları alır ve 'tamamlandı' olarak işaretler."""
    with db_lock:
        with get_db_connection() as conn:
            actions = conn.execute(
                "SELECT id, symbol, action FROM manual_actions WHERE strategy_id = ? AND status = 'pending'",
                (strategy_id,)
            ).fetchall()

            if actions:
                action_ids = tuple(action['id'] for action in actions)
                if len(action_ids) == 1:
                    conn.execute("UPDATE manual_actions SET status = 'completed' WHERE id = ?", (action_ids[0],))
                else:
                    conn.execute(f"UPDATE manual_actions SET status = 'completed' WHERE id IN {action_ids}")
                conn.commit()
            return actions
