# binance_client.py
import streamlit as st
from binance.client import Client
import requests


def create_shared_binance_client():
    """
    Artırılmış bağlantı havuzuna sahip ve yeniden kullanılabilir
    tek bir Binance Client örneği oluşturur.
    """
    try:
        # Bağlantı havuzu boyutunu artıran bir session oluştur
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=20, pool_maxsize=20)
        session.mount('https://', adapter)

        api_key = st.secrets["binance"]["api_key"]
        api_secret = st.secrets["binance"]["api_secret"]

        # İstemciyi özel session ile başlat
        return Client(api_key, api_secret, requests_params={"session": session})
    except Exception as e:
        print(f"KRİTİK HATA: Paylaşılan Binance istemcisi oluşturulamadı: {e}")
        return None


# Tüm uygulama tarafından ithal edilecek tekil istemci örneği
shared_client = create_shared_binance_client()