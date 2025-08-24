# trading_env.py (NaN Hatası Giderilmiş Nihai Hali)

import gymnasium as gym
from gymnasium import spaces
import numpy as np
import pandas as pd
import pandas_ta as ta
import math

from indicators import generate_all_indicators
from market_regime import analyze_volatility, analyze_trend


class TradingEnv(gym.Env):
    """
    Pekiştirmeli Öğrenme ajanı için zenginleştirilmiş gözlem uzayına ve
    gelişmiş ödül mekanizmasına sahip Borsa Ticaret Ortamı.
    """
    metadata = {'render_modes': ['human']}

    def __init__(self, df, initial_balance=10000, commission=0.001, strategy_params=None):
        super(TradingEnv, self).__init__()

        # strategy_params'ı sınıf seviyesinde sakla
        self.strategy_params = strategy_params if strategy_params is not None else {}
        self.df = self._prepare_data(df)
        self.initial_balance = initial_balance
        self.commission = commission

        self.action_space = spaces.Discrete(3)

        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(len(self.df.columns) + 4,),
            dtype=np.float32
        )

        self.reset()

    def _prepare_data(self, df):
        """
        Veriyi hazırlar: Göstergeleri, piyasa rejimini ve zaman özelliklerini hesaplar,
        NaN değerleri temizler.
        """
        df_copy = df.copy()

        # 1. Temel Göstergeleri Hesapla
        # DÜZELTME: Sabitlenmiş parametreler yerine dışarıdan gelenleri kullan
        # Eğer parametre gelmediyse varsayılan değerleri kullan
        strategy_params_for_indicators = {
            'sma': self.strategy_params.get('sma', 50),
            'ema': self.strategy_params.get('ema', 20),
            'bb_period': self.strategy_params.get('bb_period', 20),
            'bb_std': self.strategy_params.get('bb_std', 2.0),
            'rsi_period': self.strategy_params.get('rsi_period', 14),
            'macd_fast': self.strategy_params.get('macd_fast', 12),
            'macd_slow': self.strategy_params.get('macd_slow', 26),
            'macd_signal': self.strategy_params.get('macd_signal', 9),
            'adx_period': self.strategy_params.get('adx_period', 14),
            'stop_loss_pct': self.strategy_params.get('stop_loss_pct', 0),
            'atr_multiplier': self.strategy_params.get('atr_multiplier', 2.0),
            'cooldown_bars': self.strategy_params.get('cooldown_bars', 3),
            'signal_mode': self.strategy_params.get('signal_mode', 'and'),
            'signal_direction': self.strategy_params.get('signal_direction', 'Both'),
            'use_puzzle_bot': self.strategy_params.get('use_puzzle_bot', False),
            'use_ml': self.strategy_params.get('use_ml', False),
            'use_mta': self.strategy_params.get('use_mta', True),
            'higher_timeframe': self.strategy_params.get('higher_timeframe', '4h'),
            'trend_ema_period': self.strategy_params.get('trend_ema_period', 50),
            'commission_pct': self.strategy_params.get('commission_pct', 0.1),
            'tp1_pct': self.strategy_params.get('tp1_pct', 5.0),
            'tp1_size_pct': self.strategy_params.get('tp1_size_pct', 50),
            'tp2_pct': self.strategy_params.get('tp2_pct', 10.0),
            'tp2_size_pct': self.strategy_params.get('tp2_size_pct', 50),
            'move_sl_to_be': self.strategy_params.get('move_sl_to_be', True)
        }

        df_with_indicators = generate_all_indicators(df_copy, **strategy_params_for_indicators)

        # 2. Ham Rejim ve Zaman Özelliklerini Ekle (NaN'ler bu aşamada oluşacak)
        bbands = ta.bbands(df_with_indicators['Close'], length=self.strategy_params.get('bb_period', 20), std=self.strategy_params.get('bb_std', 2))
        bbw = (bbands['BBU_20_2.0'] - bbands['BBL_20_2.0']) / bbands['BBM_20_2.0']
        df_with_indicators['volatility_raw'] = bbw

        adx = ta.adx(df_with_indicators['High'], df_with_indicators['Low'], df_with_indicators['Close'], length=self.strategy_params.get('adx_period', 14))
        adx_col_name = f'ADX_{self.strategy_params.get("adx_period", 14)}'
        if adx_col_name in adx.columns:
            df_with_indicators['trend_strength_raw'] = adx[adx_col_name]
        else:
            df_with_indicators['trend_strength_raw'] = np.nan

        df_with_indicators['day_of_week'] = df_with_indicators.index.dayofweek
        df_with_indicators['hour_of_day'] = df_with_indicators.index.hour

        # 3. DÜZELTME: ÖNCE TÜM NaN DEĞERLERİNİ TEMİZLE
        # Önce geriye doğru doldurarak en güncel veriyi koru, sonra kalanları sil.
        df_with_indicators.fillna(method='bfill', inplace=True)
        df_with_indicators.dropna(inplace=True)

        # 4. DÜZELTME: NaN'LER TEMİZLENDİKTEN SONRA KATEGORİZASYON VE TÜR DÖNÜŞÜMÜ YAP
        # Artık bu satırlarda NaN olmadığı için .astype(int) hatasız çalışacaktır.
        df_with_indicators['volatility'] = pd.cut(df_with_indicators['volatility_raw'], bins=3, labels=[-1, 0, 1],
                                                  include_lowest=True).astype(int)
        df_with_indicators['trend_strength'] = pd.cut(df_with_indicators['trend_strength_raw'], bins=[0, 20, 30, 100],
                                                      labels=[-1, 0, 1], include_lowest=True).astype(int)

        # 5. İşlenmiş veriyi hazırla ve gereksiz ham sütunları kaldır
        df_processed = df_with_indicators.drop(columns=['volatility_raw', 'trend_strength_raw'])

        print("--- [RL Ortamı] Veri Hazırlama Tamamlandı. Gözlem Uzayı Sütunları: ---")
        print(df_processed.columns)

        return df_processed

    # ... (reset, _get_obs, step ve _calculate_sharpe_ratio fonksiyonları önceki adımdaki gibi kalacak) ...
    def reset(self, seed=None):
        super().reset(seed=seed)
        self.balance = self.initial_balance
        self.net_worth = self.initial_balance
        self.current_step = 0
        self.position = 0
        self.entry_price = 0
        self.done = False
        self.returns_history = []
        return self._get_obs(), {}

    def _get_obs(self):
        obs = self.df.iloc[self.current_step].values.astype(np.float32)
        pnl = (self.net_worth - self.initial_balance) / self.initial_balance
        additional_info = np.array([self.balance, self.position, self.entry_price, pnl], dtype=np.float32)
        return np.concatenate((obs, additional_info))

    def step(self, action):
        self.current_step += 1
        current_price = self.df['Close'].iloc[self.current_step]
        prev_net_worth = self.net_worth
        transaction_cost = 0
        reward = 0  # Ödül her adımda sıfırlanır

        # İşlem yapma (Al/Tut/Sat)
        if action == 1:  # Al
            if self.position == 0:
                # Yeni pozisyon açarken ödül sıfır, sadece komisyon cezası ekliyoruz
                self.position = 1
                self.entry_price = current_price
                transaction_cost = self.commission
        elif action == 2:  # Sat
            if self.position == 1:
                # Pozisyonu kapat
                pnl = (self.net_worth / prev_net_worth) - 1
                # Kapatılan pozisyondan elde edilen kar/zarar, doğrudan ödül olarak verilir
                reward += pnl * 100  # Yüzde olarak ödüllendir
                self.position = 0
                self.entry_price = 0
                transaction_cost = self.commission

        # Pozisyon açıksa (Tutma)
        if self.position == 1:
            # Anlık PnL'i ödül olarak ekle
            instant_pnl = (current_price - self.entry_price) / self.entry_price
            reward += instant_pnl * 100  # Anlık yüzde karı ödül olarak ekle

            # Varlık değerini güncelle
            self.net_worth = self.balance * (current_price / self.entry_price)

            # Drawdown cezası ekle (sermaye azalırsa)
            if self.net_worth < self.initial_balance:
                drawdown_penalty = (self.initial_balance - self.net_worth) / self.initial_balance
                reward -= drawdown_penalty * 5  # Cezayı daha etkili hale getirmek için çarpan kullan
        else:
            self.balance = self.net_worth

        # Komisyon cezasını uygula
        if transaction_cost > 0:
            reward -= transaction_cost * 1000  # Komisyonu cezalandır

        self.net_worth *= (1 - transaction_cost)

        # Bitirme koşulları
        self.done = self.current_step >= len(self.df) - 1 or self.net_worth <= self.initial_balance / 2

        # Epizod sonunda açık pozisyon varsa ceza
        if self.done and self.position == 1:
            reward -= 5.0  # Kapatılmamış pozisyon için ceza

        return self._get_obs(), reward, self.done, False, {}

    def _calculate_sharpe_ratio(self, returns, risk_free_rate=0.0):
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        if std_return == 0:
            return 0
        sharpe_ratio = (mean_return - risk_free_rate) / std_return
        return sharpe_ratio