import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd

from indicators import generate_all_indicators

class TradingEnv(gym.Env):
    """
    Pekiştirmeli Öğrenme ajanı için özelleştirilmiş Borsa Ticaret Ortamı.
    """
    metadata = {'render_modes': ['human']}

    def __init__(self, df, initial_balance=10000, commission=0.001):
        super(TradingEnv, self).__init__()

        self.df = self._prepare_data(df)
        self.initial_balance = initial_balance
        self.commission = commission

        # Aksiyon Alanı: [0: Bekle, 1: Al, 2: Sat]
        self.action_space = spaces.Discrete(3)

        # Gözlem Alanı: Fiyat verileri, indikatörler ve pozisyon durumu
        # Boyut = (OHLCV + İndikatör Sayısı) + (Bakiye, Pozisyon Durumu, Giriş Fiyatı)
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(len(self.df.columns) + 3,),
            dtype=np.float32
        )

        self.reset()

    def _prepare_data(self, df):
        """
        Veriyi hazırlar: Göstergeleri hesaplar ve NaN değerleri temizler.
        Mevcut indicators.py'deki fonksiyonumuzu kullanıyoruz.
        """
        # Gerekli tüm parametreler için varsayılan değerler sağlıyoruz.
        # Bu değerler, ajan eğitilirken arayüzden gelen değerlerle değiştirilebilir.
        strategy_params = {
            'sma': 50, 'ema': 20, 'bb_period': 20, 'bb_std': 2.0,
            'rsi_period': 14, 'macd_fast': 12, 'macd_slow': 26,
            'macd_signal': 9, 'adx_period': 14
        }
        df_with_indicators = generate_all_indicators(df.copy(), **strategy_params)
        df_with_indicators.fillna(method='bfill', inplace=True) # Geriye doğru doldur
        df_with_indicators.dropna(inplace=True) # Kalan NaN'ları temizle
        return df_with_indicators

    def reset(self, seed=None):
        """Ortamı başlangıç durumuna sıfırlar."""
        super().reset(seed=seed)

        self.balance = self.initial_balance
        self.net_worth = self.initial_balance
        self.current_step = 0
        self.position = 0  # -1: Short, 0: Nötr, 1: Long
        self.entry_price = 0
        self.done = False

        return self._get_obs(), {}

    def _get_obs(self):
        """Mevcut adımdaki gözlemi oluşturur."""
        obs = self.df.iloc[self.current_step].values.astype(np.float32)
        # Gözleme ek bilgiler ekle: bakiye, pozisyon, giriş fiyatı
        additional_info = np.array([self.balance, self.position, self.entry_price], dtype=np.float32)
        return np.concatenate((obs, additional_info))

    def step(self, action):
        """
        Ajanın bir aksiyon almasını ve ortamın bir sonraki duruma geçmesini sağlar.
        """
        self.current_step += 1
        current_price = self.df['Close'].iloc[self.current_step]
        prev_net_worth = self.net_worth

        # Aksiyonu gerçekleştir
        if action == 1: # AL
            if self.position == 0: # Sadece nötr iken al
                self.position = 1
                self.entry_price = current_price
                # Basitlik için tüm bakiye ile alım yapılıyor
                # Komisyonu hesaptan düş
                self.balance -= self.balance * self.commission

        elif action == 2: # SAT
            if self.position == 1: # Sadece Long pozisyondayken sat
                self.position = 0
                exit_price = current_price
                profit = (exit_price - self.entry_price) * (self.balance / self.entry_price)
                self.balance += profit
                # Komisyonu hesaptan düş
                self.balance -= self.balance * self.commission
                self.entry_price = 0

        # Portföy değerini güncelle
        if self.position == 1:
            current_value = (current_price - self.entry_price) * (self.balance / self.entry_price)
            self.net_worth = self.balance + current_value
        else:
            self.net_worth = self.balance

        # Ödülü hesapla
        reward = self.net_worth - prev_net_worth

        # Bitiş koşulunu kontrol et
        if self.current_step >= len(self.df) - 1 or self.net_worth <= self.initial_balance / 2:
            self.done = True

        return self._get_obs(), reward, self.done, False, {}