import json
import pandas as pd
import glob
import sqlite3
import os

# Veritabanı modülümüzdeki fonksiyonları bu script'te kullanmak için import ediyoruz
from database import add_or_update_strategy, update_position, DB_NAME


def migrate_strategies():
    """strategies.json dosyasını okur ve veritabanına yazar."""
    try:
        with open('strategies.json', 'r') as f:
            strategies = json.load(f)

        for strategy in strategies:
            print(f"-> Strateji migrate ediliyor: {strategy.get('name')}")
            add_or_update_strategy(strategy)

        print("✅ Stratejiler başarıyla veritabanına aktarıldı.")
        return True
    except FileNotFoundError:
        print("⚠️ strategies.json dosyası bulunamadı, bu adım atlanıyor.")
        return False
    except Exception as e:
        print(f"❌ Stratejiler migrate edilirken hata oluştu: {e}")
        return False


def migrate_positions():
    """Tüm positions_strategy_*.json dosyalarını bulur ve veritabanına yazar."""
    position_files = glob.glob('positions_strategy_*.json')
    if not position_files:
        print("ℹ️ Hiç pozisyon dosyası bulunamadı, bu adım atlanıyor.")
        return True

    print(f"Found {len(position_files)} pozisyon dosyası...")
    try:
        for file_path in position_files:
            # Dosya adından strategy_id'yi çıkar (örn: "positions_strategy_1754383301.json" -> "strategy_1754383301")
            strategy_id = os.path.basename(file_path).replace('positions_', '').replace('.json', '')

            with open(file_path, 'r') as f:
                positions = json.load(f)

            print(f"-> {strategy_id} için pozisyonlar migrate ediliyor...")
            for symbol, data in positions.items():
                if data.get('position'):  # Sadece açık pozisyonları migrate et
                    update_position(strategy_id, symbol, data['position'], data['entry_price'])

        print("✅ Tüm pozisyonlar başarıyla veritabanına aktarıldı.")
        return True
    except Exception as e:
        print(f"❌ Pozisyonlar migrate edilirken hata oluştu: {e}")
        return False


def migrate_alarms():
    """alarm_history.csv dosyasını okur ve veritabanına yazar."""
    try:
        if not os.path.exists('alarm_history.csv'):
            print("⚠️ alarm_history.csv dosyası bulunamadı, bu adım atlanıyor.")
            return True

        print("-> Alarm geçmişi (alarm_history.csv) okunuyor...")
        alarms_df = pd.read_csv('alarm_history.csv')

        # Veritabanı tablosuyla eşleşmesi için sütun adlarını düzenle
        # alarm_history.csv: Zaman, Sembol, Sinyal, Fiyat
        # alarms tablosu: timestamp, symbol, signal, price
        alarms_df.rename(columns={
            'Zaman': 'timestamp',
            'Sembol': 'symbol',
            'Sinyal': 'signal',
            'Fiyat': 'price'
        }, inplace=True)

        # DataFrame'i doğrudan SQLite tablosuna yaz (en verimli yöntem)
        with sqlite3.connect(DB_NAME) as conn:
            alarms_df.to_sql('alarms', conn, if_exists='append', index=False)

        print(f"✅ {len(alarms_df)} adet alarm kaydı başarıyla veritabanına aktarıldı.")
        return True
    except FileNotFoundError:
        print("⚠️ alarm_history.csv dosyası bulunamadı, bu adım atlanıyor.")
        return False
    except Exception as e:
        print(f"❌ Alarmlar migrate edilirken hata oluştu: {e}")
        return False


if __name__ == "__main__":
    print("--- Veri Migrasyon Scripti Başlatıldı ---")

    # Adım adım migrasyonu gerçekleştir
    strategies_ok = migrate_strategies()
    positions_ok = migrate_positions()
    alarms_ok = migrate_alarms()

    print("\n--- Migrasyon Tamamlandı ---")
    if all([strategies_ok, positions_ok, alarms_ok]):
        print("\n🎉 Tüm verileriniz başarıyla yeni veritabanına taşındı!")
        print("Artık 'migrate_data.py' scriptine ihtiyacınız yok. İsterseniz silebilirsiniz.")
        print("Eski .json ve .csv dosyalarınızı da yedekleyip silebilirsiniz.")
    else:
        print("\n⚠️ Migrasyon sırasında bazı hatalar oluştu. Lütfen yukarıdaki logları kontrol edin.")