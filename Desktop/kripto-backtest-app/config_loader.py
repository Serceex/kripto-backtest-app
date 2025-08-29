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
    if not os.path.exists(SECRETS_PATH):
        print(f"KRİTİK HATA: Sır dosyası bulunamadı! Beklenen konum: {SECRETS_PATH}")
        return {}
    try:
        return toml.load(SECRETS_PATH)
    except Exception as e:
        print(f"KRİTİK HATA: {SECRETS_PATH} dosyası okunurken hata oluştu: {e}")
        return {}

# Tüm sırlar yüklendiğinde bu değişkende saklanacak
_secrets = load_secrets()

# Diğer dosyalardan içe aktarılacak olan yapılandırma değişkenleri
DB_CONFIG = _secrets.get("postgres")
BINANCE_CONFIG = _secrets.get("binance")
TELEGRAM_CONFIG = _secrets.get("telegram")
APP_CONFIG = _secrets.get("app")

# Yükleme sırasında kontrol yapalım
if not DB_CONFIG:
    print("UYARI: 'postgres' yapılandırması secrets.toml dosyasında bulunamadı.")
if not BINANCE_CONFIG:
    print("UYARI: 'binance' yapılandırması secrets.toml dosyasında bulunamadı.")