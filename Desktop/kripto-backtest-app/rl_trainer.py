import pandas as pd
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv

# Kendi oluşturduğumuz modülleri import ediyoruz
from trading_env import TradingEnv
from utils import get_binance_klines

def train_rl_agent(symbol="BTCUSDT", interval="1h", total_timesteps=20000):
    """
    Belirtilen sembol ve zaman aralığı için bir RL ajanını eğitir ve kaydeder.

    :param symbol: Ticaret yapılacak kripto para sembolü (örn: "BTCUSDT")
    :param interval: Zaman aralığı (örn: "1h", "4h")
    :param total_timesteps: Ajanın eğitim sırasında atacağı toplam adım sayısı
    """
    print(f"--- {symbol} için RL Ajan Eğitimi Başlatılıyor ---")

    # 1. Adım: Eğitim verisini çekme
    # Mevcut utils.py dosyamızdaki fonksiyonu kullanıyoruz
    print("Geçmiş piyasa verileri indiriliyor...")
    df = get_binance_klines(symbol=symbol, interval=interval, limit=1000)

    if df.empty:
        print(f"HATA: {symbol} için veri indirilemedi. Eğitim durduruldu.")
        return

    print("Veri başarıyla indirildi. Ortam hazırlanıyor...")

    # 2. Adım: Ticaret Ortamını (Trading Environment) Hazırlama
    # Önceki adımda oluşturduğumuz TradingEnv sınıfını kullanıyoruz
    env = DummyVecEnv([lambda: TradingEnv(df)])

    # 3. Adım: RL Modelini (Ajan) Oluşturma
    # Stable-Baselines3 kütüphanesinden PPO modelini kullanıyoruz
    # 'MlpPolicy', standart bir sinir ağı yapısı kullanacağını belirtir.
    model = PPO("MlpPolicy", env, verbose=1, tensorboard_log="./rl_tensorboard_logs/")
    print("PPO modeli oluşturuldu. Eğitim süreci başlıyor...")
    print(f"Tahmini eğitim süresi: {total_timesteps} adım.")

    # 4. Adım: Modeli Eğitme
    # Ajan, bu adımda ortam içinde deneme-yanılma yoluyla öğrenir
    model.learn(total_timesteps=total_timesteps)
    print("Eğitim tamamlandı!")

    # 5. Adım: Eğitilmiş Modeli Kaydetme
    # Eğitilen stratejiyi daha sonra kullanmak üzere bir dosyaya kaydediyoruz
    model_save_path = f"./rl_model_{symbol}_{interval}.zip"
    model.save(model_save_path)
    print(f"Eğitilmiş model başarıyla '{model_save_path}' adresine kaydedildi.")

if __name__ == '__main__':
    # Bu script'i doğrudan çalıştırdığımızda bir test eğitimi başlat
    train_rl_agent(symbol="BTCUSDT", interval="1h", total_timesteps=25000)