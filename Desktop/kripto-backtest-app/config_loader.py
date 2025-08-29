# config_loader.py
import toml
import os

# Bu dosyanın bulunduğu dizini alarak projenin ana dizinini bul
try:
    PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
except NameError:
    PROJECT_ROOT = os.path.abspath('.')

SECRETS_PATH = os.path.join(PROJECT_ROOT, '.streamlit', 'secrets.toml')


def load_secrets():
    """
    .streamlit/secrets.toml dosyasını yükler ve yapılandırmayı döndürür.
    """
    print(f"--- [DEBUG] Sır dosyası aranıyor: {SECRETS_PATH}")
    if not os.path.exists(SECRETS_PATH):
        print(f"--- [KRİTİK HATA] Sır dosyası bulunamadı! Lütfen bu konumun doğru olduğunu kontrol edin.")
        return {}

    print("--- [DEBUG] Sır dosyası bulundu. İçerik okunuyor...")
    try:
        secrets_content = toml.load(SECRETS_PATH)
        print("--- [DEBUG] Sır dosyası başarıyla okundu.")
        return secrets_content
    except Exception as e:
        print(f"--- [KRİTİK HATA] {SECRETS_PATH} dosyası okunurken/ayrıştırılırken hata oluştu: {e}")
        return {}


# Tüm sırlar yüklendiğinde bu değişkende saklanacak
_secrets = load_secrets()

# Diğer dosyalardan içe aktarılacak olan yapılandırma değişkenleri
DB_CONFIG = _secrets.get("postgres")
BINANCE_CONFIG = _secrets.get("binance")
TELEGRAM_CONFIG = _secrets.get("telegram")
APP_CONFIG = _secrets.get("app")

# Yükleme sonrası kontrol yapalım
print("\n--- [DEBUG] Yüklenen Yapılandırma Kontrolü ---")
if DB_CONFIG:
    print("✅ 'postgres' bölümü başarıyla yüklendi.")
else:
    print("❌ 'postgres' bölümü secrets.toml dosyasında bulunamadı veya yüklenemedi.")

if BINANCE_CONFIG:
    print("✅ 'binance' bölümü başarıyla yüklendi.")
else:
    print("❌ 'binance' bölümü secrets.toml dosyasında bulunamadı veya yüklenemedi.")

if TELEGRAM_CONFIG:
    print("✅ 'telegram' bölümü başarıyla yüklendi.")
else:
    print("❌ 'telegram' bölümü secrets.toml dosyasında bulunamadı veya yüklenemedi.")
print("--- [DEBUG] Kontrol Tamamlandı ---\n")