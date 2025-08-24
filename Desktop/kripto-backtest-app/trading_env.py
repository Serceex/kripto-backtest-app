# trading_env.py (Gelişmiş Ödül Mekanizması ile Güncellenmiş Nihai Hali)

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd
import pandas_ta as ta

from indicators import generate_all_indicators
from market_regime import analyze_volatility, analyze_trend

class TradingEnv(gym.Env):
    """
    Pekiştirmeli Öğrenme ajanı için zenginleştirilmiş gözlem uzayına ve
    gelişmiş ödül mekanizmasına sahip Borsa Ticaret Ortamı.
    """
    metadata = {'render_modes': ['human']}

    def __init__(self, df, initial_balance=10000, commission=0.001):
        super(TradingEnv, self).__init__()

        self.df = self._prepare_data(df)
        self.initial_balance = initial_balance
        self.commission = commission

        self.action_space = spaces.Discrete(3)

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(len(self.df.columns) + 4,), # YENİ: PnL'i de gözleme ekledik
            dtype=np.float32
        )

        self.reset()

    def _prepare_data(self, df):
        # (Bu fonksiyon bir önceki adımdaki gibi kalıyor)
        df_copy = df.copy()
        strategy_params = {
            'sma': 50, 'ema': 20, 'bb_period': 20, 'bb_std': 2.0,
            'rsi_period': 14, 'macd_fast': 12, 'macd_slow': 26,
            'macd_signal': 9, 'adx_period': 14
        }
        df_with_indicators = generate_all_indicators(df_copy, **strategy_params)
        bbands = ta.bbands(df_with_indicators['Close'], length=20, std=2)
        bbw = (bbands['BBU_20_2.0'] - bbands['BBL_20_2.0']) / bbands['BBM_20_2.0']
        df_with_indicators['volatility_raw'] = bbw
        df_with_indicators['volatility'] = pd.cut(bbw, bins=3, labels=[-1, 0, 1], include_lowest=True).astype(int)
        adx = ta.adx(df_with_indicators['High'], df_with_indicators['Low'], df_with_indicators['Close'], length=14)
        df_with_indicators['trend_strength_raw'] = adx[f'ADX_14']
        df_with_indicators['trend_strength'] = pd.cut(adx[f'ADX_14'], bins=[0, 20, 30, 100], labels=[-1, 0, 1], include_lowest=True).astype(int)
        df_with_indicators['day_of_week'] = df_with_indicators.index.dayofweek
        df_with_indicators['hour_of_day'] = df_with_indicators.index.hour
        df_processed = df_with_indicators.drop(columns=['volatility_raw', 'trend_strength_raw'])
        df_processed.fillna(method='bfill', inplace=True)
        df_processed.dropna(inplace=True)
        return df_processed

    def reset(self, seed=None):
        super().reset(seed=seed)
        self.balance = self.initial_balance
        self.net_worth = self.initial_balance
        self.current_step = 0
        self.position = 0
        self.entry_price = 0
        self.done = False
        # YENİ: Ödül hesaplaması için getiri geçmişini tut
        self.returns_history = []
        return self._get_obs(), {}

    def _get_obs(self):
        obs = self.df.iloc[self.current_step].values.astype(np.float32)
        # YENİ: Anlık PnL'i de gözlem uzayına ekliyoruz
        pnl = (self.net_worth - self.initial_balance) / self.initial_balance
        additional_info = np.array([self.balance, self.position, self.entry_price, pnl], dtype=np.float32)
        return np.concatenate((obs, additional_info))

    def step(self, action):
        self.current_step += 1
        current_price = self.df['Close'].iloc[self.current_step]
        prev_net_worth = self.net_worth

        # --- YENİ: Aksiyon Cezası ---
        transaction_cost = 0

        if action == 1: # AL
            if self.position == 0:
                self.position = 1
                self.entry_price = current_price
                transaction_cost = self.commission
        elif action == 2: # SAT
            if self.position == 1:
                self.position = 0
                transaction_cost = self.commission
                self.entry_price = 0

        # Portföy değerini güncelle
        if self.position == 1:
            self.net_worth = self.balance * (current_price / self.entry_price)
        else: # Pozisyonda değilken, bakiye son kapanan işlemin net değeri olur
            self.balance = self.net_worth

        # Portföy değerinden işlem maliyetini düş
        self.net_worth *= (1 - transaction_cost)

        # --- YENİ: RİSK AYARLI ÖDÜL HESAPLAMASI ---
        daily_return = (self.net_worth / prev_net_worth) - 1
        self.returns_history.append(daily_return)

        if len(self.returns_history) > 1:
            sharpe_ratio = self._calculate_sharpe_ratio(self.returns_history)
            reward = sharpe_ratio
        else:
            reward = 0 # İlk adımda ödül yok

        # Bitiş koşulunu kontrol et
        if self.current_step >= len(self.df) - 1 or self.net_worth <= self.initial_balance / 2:
            self.done = True

        # Eğer son adımdaysa ve hala pozisyondaysa, büyük bir ceza ver (pozisyonu kapatmaya teşvik)
        if self.done and self.position == 1:
            reward -= 0.1

        return self._get_obs(), reward, self.done, False, {}

    def _calculate_sharpe_ratio(self, returns, risk_free_rate=0.0):
        """Verilen bir getiri serisi için Sharpe Oranı'nı hesaplar."""
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        if std_return == 0:
            return 0 # Risk yoksa Sharpe oranı sıfırdır
        sharpe_ratio = (mean_return - risk_free_rate) / std_return
        # Yıllıklandırmaya gerek yok, çünkü adım bazında karşılaştırma yapıyoruz
        return sharpe_ratio