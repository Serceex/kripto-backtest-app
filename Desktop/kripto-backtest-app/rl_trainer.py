# rl_trainer.py (Modelleri Veritabanına Kaydeden Nihai Hali)

import pandas as pd
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
import io

# Kendi oluşturduğumuz modülleri import ediyoruz
from trading_env import TradingEnv
from utils import get_binance_klines
# YENİ: Veritabanına model kaydetmek için fonksiyonumuzu import ediyoruz
from database import save_rl_model


def train_rl_agent(symbol="BTCUSDT", interval="1h", total_timesteps=20000, strategy_params=None):
    """
    Belirtilen sembol ve zaman aralığı için bir RL ajanını eğitir ve
    eğitilmiş modeli doğrudan veritabanına kaydeder.
    """
    print(f"--- {symbol} için RL Ajan Eğitimi Başlatılıyor ---")

    # 1. Adım: Eğitim verisini çekme
    print("Geçmiş piyasa verileri indiriliyor...")
    df = get_binance_klines(symbol=symbol, interval=interval, limit=1000)
    if df.empty:
        print(f"HATA: {symbol} için veri indirilemedi. Eğitim durduruldu.")
        return

    print("Veri başarıyla indirildi. Ortam hazırlanıyor...")

    # 2. Adım: Ticaret Ortamını Hazırlama
    # DÜZELTME: strategy_params parametresini TradingEnv'e aktar
    env = DummyVecEnv([lambda: TradingEnv(df, strategy_params=strategy_params)])


    # 3. Adım: RL Modelini Oluşturma
    model = PPO("MlpPolicy", env, verbose=1, tensorboard_log="./rl_tensorboard_logs/")
    print("PPO modeli oluşturuldu. Eğitim süreci başlıyor...")
    print(f"Tahmini eğitim süresi: {total_timesteps} adım.")

    # 4. Adım: Modeli Eğitme
    model.learn(total_timesteps=total_timesteps)
    print("Eğitim tamamlandı!")

    # 5. Adım: Eğitilmiş Modeli Veritabanına Kaydetme
    print("Eğitilmiş model veritabanına kaydediliyor...")
    try:
        # Modeli bir .zip dosyasına değil, bir hafıza buffer'ına kaydet
        model_buffer = io.BytesIO()
        model.save(model_buffer)

        # Buffer'ı sıfırla ki baştan okunabilsin
        model_buffer.seek(0)

        # Veritabanına kaydetmek için benzersiz bir isim ve açıklama oluştur
        model_name = f"PPO_{symbol}_{interval}_{total_timesteps}steps"
        model_description = f"{symbol} paritesi, {interval} zaman diliminde {total_timesteps} adım ile eğitilmiş PPO ajanı."

        # Yeni veritabanı fonksiyonumuzu çağır
        save_rl_model(model_name, model_description, model_buffer)

        print(f"✅ Eğitilmiş model '{model_name}' ismiyle başarıyla veritabanına kaydedildi.")

    except Exception as e:
        print(f"❌ KRİTİK HATA: Model veritabanına kaydedilirken bir sorun oluştu: {e}")



if __name__ == '__main__':
    # Bu script'i doğrudan çalıştırdığımızda bir test eğitimi başlat
    train_rl_agent(symbol="BTCUSDT", interval="1h", total_timesteps=25000)