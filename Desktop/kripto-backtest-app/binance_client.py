# binance_client.py
import toml
import os
import requests
from binance.client import Client

# secrets.toml dosyasının tam yolunu bul
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    SECRETS_PATH = os.path.join(script_dir, '.streamlit', 'secrets.toml')
except Exception:
    SECRETS_PATH = os.path.join('.streamlit', 'secrets.toml')


def get_binance_secrets():
    """
    API anahtarlarını önce Streamlit'in kendi mekanizmasından,
    başarısız olursa doğrudan .streamlit/secrets.toml dosyasından okur.
    Bu, hem Streamlit arayüzünün hem de arkaplan worker'larının çalışmasını sağlar.
    """
    # 1. Streamlit secrets'ı dene (Streamlit ortamı için)
    try:
        import streamlit as st
        if "binance" in st.secrets:
            return st.secrets["binance"]
    except Exception:
        # Streamlit ortamında değilsek bu blok atlanacak
        pass

    # 2. .streamlit/secrets.toml dosyasını doğrudan oku (Worker ortamı için)
    try:
        secrets = toml.load(SECRETS_PATH)
        return secrets["binance"]
    except Exception as e:
        print(f"KRİTİK HATA: {SECRETS_PATH} dosyasından Binance sırları okunamadı: {e}")
        return None


def create_shared_binance_client():
    """
    Artırılmış bağlantı havuzuna sahip ve yeniden kullanılabilir
    tek bir Binance Client örneği oluşturur.
    """
    binance_config = get_binance_secrets()
    if not binance_config or "api_key" not in binance_config:
        print("KRİTİK HATA: Binance API anahtarları yapılandırmada bulunamadı.")
        return None

    try:
        # Bağlantı havuzu boyutunu artıran bir session oluştur
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
        session.mount('https://', adapter)

        api_key = binance_config["api_key"]
        api_secret = binance_config["api_secret"]

        # İstemciyi özel session ile başlat
        return Client(api_key, api_secret, requests_params={"session": session})
    except Exception as e:
        print(f"KRİTİK HATA: Paylaşılan Binance istemcisi oluşturulamadı: {e}")
        return None


# Tüm uygulama tarafından ithal edilecek tekil istemci örneği
shared_client = create_shared_binance_client()