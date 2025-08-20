# trade_executor.py

from binance.client import Client
from binance.exceptions import BinanceAPIException
import streamlit as st  # secrets.toml'a erişim için gerekli


def get_binance_client():
    """API anahtarlarını kullanarak Binance istemcisini oluşturur."""
    try:
        api_key = st.secrets["binance"]["api_key"]
        api_secret = st.secrets["binance"]["api_secret"]
        return Client(api_key, api_secret)
    except Exception as e:
        print(f"HATA: Binance API anahtarları okunamadı: {e}")
        return None


def set_futures_leverage_and_margin(symbol: str, leverage: int, margin_type: str = 'ISOLATED'):
    """Bir parite için kaldıraç ve marjin tipini ayarlar."""
    client = get_binance_client()
    if not client: return False

    try:
        # Önce marjin tipini ayarla
        client.futures_change_margin_type(symbol=symbol, marginType=margin_type)
        # Sonra kaldıracı ayarla
        client.futures_change_leverage(symbol=symbol, leverage=leverage)
        print(f"BİLGİ: {symbol} için kaldıraç {leverage}x ve marjin tipi {margin_type} olarak ayarlandı.")
        return True
    except BinanceAPIException as e:
        # Eğer kaldıraç zaten istenen değerdeyse, bu bir hata değildir.
        if e.code == -4046:
            print(f"BİLGİ: {symbol} için kaldıraç zaten {leverage}x olarak ayarlı.")
            return True
        print(f"HATA: {symbol} için kaldıraç ayarlanırken hata oluştu: {e}")
        return False


def get_open_position_amount(symbol: str):
    """Belirtilen sembol için açık olan pozisyonun miktarını döndürür."""
    client = get_binance_client()
    if not client: return 0.0

    try:
        positions = client.futures_position_information(symbol=symbol)
        if positions:
            # Pozisyon miktarı 'positionAmt' string olarak döner, float'a çevirip mutlak değerini alıyoruz.
            return abs(float(positions[0]['positionAmt']))
        return 0.0
    except BinanceAPIException as e:
        print(f"HATA: {symbol} pozisyon bilgisi alınamadı: {e}")
        return 0.0


def place_futures_order(symbol: str, side: str, quantity: float):
    """
    Binance Vadeli İşlemler'e piyasa emri gönderir.
    side: 'BUY' veya 'SELL'
    """
    client = get_binance_client()
    if not client: return None

    try:
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type=Client.ORDER_TYPE_MARKET,
            quantity=quantity
        )
        print(f"EMİR BAŞARILI: {symbol} | Taraf: {side} | Miktar: {quantity} | Emir ID: {order['orderId']}")
        return order
    except BinanceAPIException as e:
        print(f"EMİR HATASI: {symbol} için {side} emri gönderilemedi: {e}")
        return None