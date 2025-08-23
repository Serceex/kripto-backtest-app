import sqlite3
import psycopg2
import psycopg2.extras
import json
import streamlit as st  # secrets.toml okumak için

print("--- SQLite'tan PostgreSQL'e Veri Taşıma Scripti Başlatıldı ---")

# --- KAYNAK (SQLite) ---
SQLITE_DB = "veritas_point.db"

# --- HEDEF (PostgreSQL) ---
try:
    db_config = st.secrets["postgres"]
    PG_DBNAME = db_config["database"]
    PG_USER = db_config["user"]
    PG_PASSWORD = db_config["password"]
    PG_HOST = db_config["host"]
    PG_PORT = db_config["port"]
except Exception as e:
    print(f"HATA: PostgreSQL bağlantı bilgileri .streamlit/secrets.toml dosyasından okunamadı: {e}")
    exit()


def migrate_table(table_name, sqlite_cur, pg_cur):
    """Tek bir tabloyu, veri tiplerini dönüştürerek migrate eder."""
    print(f"\n-> '{table_name}' tablosu işleniyor...")
    sqlite_cur.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cur.fetchall()

    if not rows:
        print(f"'{table_name}' tablosunda taşınacak veri bulunamadı. Atlanıyor.")
        return

    columns = [description[0] for description in sqlite_cur.description]

    # --- YENİ: Veri Dönüştürme Mantığı ---
    processed_rows = []
    # Dönüştürülecek boolean sütunların isimlerini tanımla
    bool_columns = ['is_trading_enabled', 'tp1_hit', 'tp2_hit']

    for row in rows:
        processed_row = list(row)  # Satırı değiştirilebilir bir listeye çevir
        for i, col_name in enumerate(columns):
            if col_name in bool_columns:
                # Eğer sütun bir boolean sütunu ise, 0/1 değerini True/False'a çevir
                if processed_row[i] is not None:
                    processed_row[i] = bool(processed_row[i])
        processed_rows.append(tuple(processed_row))  # Listeyi tekrar tuple'a çevirip ekle
    # --- DÖNÜŞTÜRME SONU ---

    s_placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({s_placeholders})"

    try:
        # Dönüştürülmüş veriyi PostgreSQL'e toplu olarak ekle
        psycopg2.extras.execute_batch(pg_cur, insert_sql, processed_rows)
        print(f"✅ '{table_name}' tablosundan {len(rows)} kayıt başarıyla taşındı.")
    except Exception as e:
        print(f"❌ HATA: '{table_name}' tablosu işlenirken hata oluştu: {e}")


def main():
    try:
        sqlite_conn = sqlite3.connect(SQLITE_DB)
        sqlite_conn.row_factory = lambda cursor, row: row  # Veriyi tuple olarak almak için
        sqlite_cur = sqlite_conn.cursor()

        pg_conn = psycopg2.connect(dbname=PG_DBNAME, user=PG_USER, password=PG_PASSWORD, host=PG_HOST, port=PG_PORT)
        pg_cur = pg_conn.cursor()

        # Tabloları temizleyerek mükerrer kayıtları önle (opsiyonel ama tavsiye edilir)
        print("\n--- Hedef tablolardaki eski veriler temizleniyor... ---")
        pg_cur.execute("DELETE FROM manual_actions;")
        pg_cur.execute("DELETE FROM alarms;")
        pg_cur.execute("DELETE FROM positions;")
        pg_cur.execute("DELETE FROM strategies;")

        migrate_table("strategies", sqlite_cur, pg_cur)
        migrate_table("positions", sqlite_cur, pg_cur)
        migrate_table("alarms", sqlite_cur, pg_cur)
        migrate_table("manual_actions", sqlite_cur, pg_cur)

        pg_conn.commit()

    except sqlite3.OperationalError as e:
        print(f"HATA: SQLite veritabanı '{SQLITE_DB}' bulunamadı veya okunamadı. {e}")
    except Exception as e:
        print(f"Kritik bir hata oluştu: {e}")
        if 'pg_conn' in locals():
            pg_conn.rollback()  # Hata durumunda işlemi geri al
    finally:
        if 'sqlite_conn' in locals():
            sqlite_conn.close()
        if 'pg_conn' in locals():
            pg_conn.close()
        print("\n--- Taşıma Scripti Tamamlandı ---")


if __name__ == "__main__":
    main()