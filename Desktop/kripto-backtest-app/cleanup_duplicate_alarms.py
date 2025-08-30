# cleanup_duplicate_alarms.py

from database import get_db_connection


def clean_duplicate_alarms():
    """
    Alarms tablosundaki mükerrer kayıtları, aynı saniye içinde gerçekleşen
    birebir aynı logları bularak temizler. Her gruptan sadece bir kayıt bırakır.
    """
    deleted_count = 0

    # PostgreSQL'in ctid özelliğini kullanarak mükerrer kayıtları silen sorgu.
    # Aynı saniye içinde atılan birebir aynı loglardan sadece en eskisini tutar, diğerlerini siler.
    sql_query = """
    DELETE FROM alarms a
    WHERE a.ctid <> (
       SELECT min(b.ctid)
       FROM alarms b
       WHERE
            a.strategy_id = b.strategy_id AND
            a.symbol = b.symbol AND
            a.signal = b.signal AND
            a.price = b.price AND
            date_trunc('second', a.timestamp) = date_trunc('second', b.timestamp)
    );
    """

    print("--- Mükerrer Alarm Kayıtları Temizleme Scripti ---")

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                print("🧹 Temizleme işlemi başlatılıyor...")
                cursor.execute(sql_query)
                deleted_count = cursor.rowcount  # Silinen satır sayısını al
                conn.commit()
                print("✅ Temizleme işlemi başarıyla tamamlandı.")
    except Exception as e:
        print(f"❌ Temizleme sırasında bir hata oluştu: {e}")

    print("---------------------------------------------")
    print(f"📊 Toplam {deleted_count} adet mükerrer alarm kaydı silindi.")
    print("---------------------------------------------")


if __name__ == "__main__":
    clean_duplicate_alarms()