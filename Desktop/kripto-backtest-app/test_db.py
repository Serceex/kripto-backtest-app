# Bu script, sadece veritabanı bağlantısını ve tablo oluşturma işlemini test eder.

print("--- Veritabanı bağlantı testi başlıyor... ---")

# database.py dosyasındaki fonksiyonları import ediyoruz
from database import initialize_db

# Tablo oluşturma/doğrulama fonksiyonunu çağırıyoruz
initialize_db()

print("--- Veritabanı bağlantı testi tamamlandı. ---")