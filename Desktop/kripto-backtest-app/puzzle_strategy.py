import numpy as np
import pandas as pd

class PuzzleStrategy:
    def __init__(self, config):
        """
        config: {
            'indicators': ['RSI', 'MACD', 'Bollinger', 'ADX'],
            'weights': {'RSI': 0.25, 'MACD': 0.25, 'Bollinger': 0.25, 'ADX': 0.25},
            'thresholds': {
                'RSI': {'buy': 30, 'sell': 70},
                'MACD': {},  # Sadece yön karşılaştırması
                'Bollinger': {},  # Alt/üst band kullanımı
                'ADX': {'min': 20}
            },
            'signal_mode': 'Long & Short',
            'min_score': 0.5
        }
        """
        self.config = config

    def compute_score(self, row):
        score = 0
        total_weight = 0

        # RSI
        if 'RSI' in self.config['indicators']:
            thresholds = self.config['thresholds']['RSI']
            if row['RSI'] < thresholds['buy']:
                score += self.config['weights']['RSI']
            elif row['RSI'] > thresholds['sell']:
                score -= self.config['weights']['RSI']
            total_weight += self.config['weights']['RSI']

        # MACD
        if 'MACD' in self.config['indicators']:
            if row['MACD'] > row['MACD_signal']:
                score += self.config['weights']['MACD']
            elif row['MACD'] < row['MACD_signal']:
                score -= self.config['weights']['MACD']
            total_weight += self.config['weights']['MACD']

        # Bollinger Bands
        if 'Bollinger' in self.config['indicators']:
            if row['Close'] <= row.get('bb_lband', np.nan):
                score += self.config['weights']['Bollinger']
            elif row['Close'] >= row.get('bb_hband', np.nan):
                score -= self.config['weights']['Bollinger']
            total_weight += self.config['weights']['Bollinger']

        # ADX
        if 'ADX' in self.config['indicators']:
            if row['ADX'] > self.config['thresholds']['ADX']['min']:
                score += self.config['weights']['ADX']
            total_weight += self.config['weights']['ADX']

        return score / total_weight if total_weight > 0 else 0

    def generate(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['PuzzleScore'] = df.apply(self.compute_score, axis=1)
        df['PuzzleSignal'] = 'Bekle'

        for i in range(len(df)):
            score = df.loc[df.index[i], 'PuzzleScore']
            if score >= self.config['min_score']:
                df.at[df.index[i], 'PuzzleSignal'] = 'Al'
            elif score <= -self.config['min_score'] and self.config['signal_mode'] == 'Long & Short':
                df.at[df.index[i], 'PuzzleSignal'] = 'Short'

        return df
