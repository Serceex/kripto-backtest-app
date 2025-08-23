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
    """Tek bir tabloyu migrate eder."""
    print(f"\n-> '{table_name}' tablosu işleniyor...")
    sqlite_cur.execute(f"SELECT * FROM {table_name}")
    rows = sqlite_cur.fetchall()

    if not rows:
        print(f"'{table_name}' tablosunda taşınacak veri bulunamadı. Atlanıyor.")
        return

    # Sütun isimlerini al
    columns = [description[0] for description in sqlite_cur.description]

    # PostgreSQL için INSERT sorgusunu oluştur
    s_placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({s_placeholders})"

    # Veriyi PostgreSQL'e toplu olarak ekle (daha verimli)
    try:
        psycopg2.extras.execute_batch(pg_cur, insert_sql, rows)
        print(f"✅ '{table_name}' tablosundan {len(rows)} kayıt başarıyla taşındı.")
    except Exception as e:
        print(f"❌ HATA: '{table_name}' tablosu işlenirken hata oluştu: {e}")
        print("Veri satırları:")
        for row in rows[:5]:  # Hata ayıklama için ilk 5 satırı göster
            print(row)


def main():
    try:
        # Veritabanlarına bağlan
        sqlite_conn = sqlite3.connect(SQLITE_DB)
        sqlite_conn.row_factory = sqlite3.Row  # Sütun isimlerine erişim için
        sqlite_cur = sqlite_conn.cursor()

        pg_conn = psycopg2.connect(dbname=PG_DBNAME, user=PG_USER, password=PG_PASSWORD, host=PG_HOST, port=PG_PORT)
        pg_cur = pg_conn.cursor()

        # Tabloları migrate et (önce ana tablo, sonra bağımlı tablolar)
        # ÖNEMLİ: Tabloların PostgreSQL'de `initialize_db()` tarafından zaten oluşturulduğunu varsayıyoruz.
        migrate_table("strategies", sqlite_cur, pg_cur)
        migrate_table("positions", sqlite_cur, pg_cur)
        migrate_table("alarms", sqlite_cur, pg_cur)
        migrate_table("manual_actions", sqlite_cur, pg_cur)

        # Değişiklikleri kaydet ve bağlantıları kapat
        pg_conn.commit()

    except sqlite3.OperationalError as e:
        print(f"HATA: SQLite veritabanı '{SQLITE_DB}' bulunamadı veya okunamadı. {e}")
    except Exception as e:
        print(f"Kritik bir hata oluştu: {e}")
    finally:
        if 'sqlite_conn' in locals():
            sqlite_conn.close()
        if 'pg_conn' in locals():
            pg_conn.close()
        print("\n--- Taşıma Scripti Tamamlandı ---")


if __name__ == "__main__":
    main()