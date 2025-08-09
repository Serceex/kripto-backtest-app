import sqlite3
import os

# Veritabanı dosyasının yolunu database.py'den alıyoruz
# Bu sayede script her zaman doğru veritabanını hedefler
try:
    project_dir = os.path.dirname(os.path.abspath(__file__))
    DB_NAME = os.path.join(project_dir, "veritas_point.db")
    print(f"✅ Veritabanı yolu bulundu: {DB_NAME}")
except Exception as e:
    DB_NAME = "veritas_point.db"
    print(f"⚠️ Veritabanı yolu bulunamadı, varsayılan kullanılıyor: {e}")


def migrate_schema():
    """
    Alarms tablosuna 'strategy_id' sütununu ekler.
    Bu işlem sadece sütun mevcut değilse yapılır, böylece script'i
    birden çok kez çalıştırmak güvenlidir.
    """
    print("\n--- Veritabanı Şema Güncelleme Başlatıldı ---")
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()

        # 1. Alarms tablosunda 'strategy_id' sütununun olup olmadığını kontrol et
        cursor.execute("PRAGMA table_info(alarms)")
        columns = [info[1] for info in cursor.fetchall()]

        if 'strategy_id' in columns:
            print("✅ 'strategy_id' sütunu zaten mevcut. Hiçbir işlem yapılmadı.")
        else:
            # 2. Eğer sütun yoksa, ekle
            print("⏳ 'strategy_id' sütunu bulunamadı. Tabloya ekleniyor...")
            # FOREIGN KEY kısıtlamasını da ekleyerek veri bütünlüğünü sağlıyoruz
            cursor.execute("ALTER TABLE alarms ADD COLUMN strategy_id TEXT REFERENCES strategies(id)")
            conn.commit()
            print("🎉 BAŞARILI: 'strategy_id' sütunu 'alarms' tablosuna eklendi.")

    except sqlite3.Error as e:
        print(f"❌ VERİTABANI HATASI: Şema güncellenirken bir hata oluştu: {e}")
    finally:
        if conn:
            conn.close()
            print("\n--- Güncelleme Tamamlandı. Bağlantı kapatıldı. ---")


if __name__ == "__main__":
    migrate_schema()