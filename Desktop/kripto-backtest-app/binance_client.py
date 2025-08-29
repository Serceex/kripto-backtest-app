# binance_client.py
import requests
from binance.client import Client

# YENİ: Sırları merkezi yükleyiciden alıyoruz
from config_loader import BINANCE_CONFIG


def create_shared_binance_client():
    """
    Merkezi yapılandırmayı kullanarak tek bir Binance Client örneği oluşturur.
    """
    if not BINANCE_CONFIG or "api_key" not in BINANCE_CONFIG:
        print("KRİTİK HATA: Binance API anahtarları yapılandırmada bulunamadı.")
        return None

    try:
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
        session.mount('https://', adapter)

        api_key = BINANCE_CONFIG["api_key"]
        api_secret = BINANCE_CONFIG["api_secret"]

        return Client(api_key, api_secret, requests_params={"session": session})
    except Exception as e:
        print(f"KRİTİK HATA: Paylaşılan Binance istemcisi oluşturulamadı: {e}")
        return None


# Tüm uygulama tarafından ithal edilecek tekil istemci örneği
shared_client = create_shared_binance_client()