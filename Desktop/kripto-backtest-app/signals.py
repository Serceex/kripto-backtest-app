# signals.py (Sinyal Mantığı Revize Edilmiş Tam Hali)

import numpy as np
import pandas as pd

# PuzzleStrategy'yi ana sinyal mekanizması olarak kullanabilmek için import ediyoruz.
# puzzle_strategy.py dosyasının bu dosya ile aynı dizinde olduğundan emin olun.
try:
    from puzzle_strategy import PuzzleStrategy
except ImportError:
    print("UYARI: puzzle_strategy.py bulunamadı. Puzzle Bot özelliği çalışmayacaktır.")
    PuzzleStrategy = None


def generate_signals(df,
                     use_puzzle_bot=False,
                     puzzle_config=None,
                     **kwargs):
    """
    Sinyal üretme fonksiyonu.
    'use_puzzle_bot' True ise PuzzleStrategy'yi, değilse standart gösterge mantığını kullanır.
    """
    df = df.copy()

    # --- BÖLÜM 1: PUZZLE STRATEJİ BOTU MANTIĞI ---
    if use_puzzle_bot:
        # Eğer PuzzleStrategy başarıyla import edilemediyse veya etkin değilse, kullanıcıyı bilgilendir.
        if PuzzleStrategy is None:
            print("HATA: PuzzleStrategy sınıfı yüklenemediği için Puzzle Bot çalıştırılamıyor.")
            df['Signal'] = 'Bekle'
            df['Buy_Signal'] = False
            df['Sell_Signal'] = False
            return df

        # Arayüzden özel bir konfigürasyon gelmezse, varsayılan bir tane kullan.
        if puzzle_config is None:
            print("UYARI: Puzzle Strateji için özel bir konfigürasyon bulunamadı. Varsayılan kullanılıyor.")
            puzzle_config = {
                'indicators': ['RSI', 'MACD'],
                'weights': {'RSI': 0.5, 'MACD': 0.5},
                'thresholds': {
                    'RSI': {'buy': kwargs.get('rsi_buy', 30), 'sell': kwargs.get('rsi_sell', 70)},
                    'MACD': {},
                    'ADX': {'min': 20}
                },
                'signal_mode': kwargs.get('signal_direction', 'Both'),
                'min_score': 0.6  # Pozisyona girmek için gereken minimum skor
            }

        print("🧩 Puzzle Strateji Botu çalıştırılıyor...")
        puzzle_bot = PuzzleStrategy(config=puzzle_config)
        df_with_puzzle_signals = puzzle_bot.generate(df)

        # Puzzle bot'un ürettiği sinyalleri ana DataFrame'e ata
        df['Signal'] = df_with_puzzle_signals['PuzzleSignal']
        df['Buy_Signal'] = (df['Signal'] == 'Al')
        # Hem 'Sat' (Long kapatma) hem de 'Short' (yeni Short pozisyon) sinyallerini Sell_Signal olarak kabul et
        df['Sell_Signal'] = (df['Signal'] == 'Sat') | (df['Signal'] == 'Short')

        print(f"📈 Puzzle Bot - Ham Al Sinyali: {df['Buy_Signal'].sum()}")
        print(f"📉 Puzzle Bot - Ham Sat/Short Sinyali: {df['Sell_Signal'].sum()}")

        return df

    # --- BÖLÜM 2: STANDART GÖSTERGE MANTIĞI ---

    # Eksik kolonları doldurarak hataların önüne geç
    required_cols = ['RSI', 'MACD', 'MACD_signal', 'bb_lband', 'bb_hband', 'ADX',
                     'Stoch_k', 'VWAP', 'SMA_fast', 'SMA_slow']
    for col in required_cols:
        if col not in df.columns:
            df[col] = np.nan

    # Strateji parametrelerini kwargs'tan al, yoksa varsayılan değerleri kullan
    signal_mode = kwargs.get('signal_mode', 'and')  # Varsayılan: AND (Teyitli Sinyal)
    signal_direction = kwargs.get('signal_direction', 'Both')

    buy_conditions = []
    sell_conditions = []

    # --- YENİ: Kesişimleri tespit etmek için bir önceki barın verisini kullan ---
    df['SMA_fast_prev'] = df['SMA_fast'].shift(1)
    df['SMA_slow_prev'] = df['SMA_slow'].shift(1)

    # Long (Al) sinyali şartları
    if kwargs.get('use_rsi', False):
        buy_conditions.append(df['RSI'] < kwargs.get('rsi_buy', 30))
    if kwargs.get('use_macd', False):
        buy_conditions.append(df['MACD'] > df['MACD_signal'])
    if kwargs.get('use_bb', False):
        buy_conditions.append(df['Close'] < df['bb_lband'])
    if kwargs.get('use_adx', False):
        buy_conditions.append(df['ADX'] > kwargs.get('adx_threshold', 25))
    if kwargs.get('use_stoch', False):
        buy_conditions.append(df['Stoch_k'] < kwargs.get('stoch_buy_level', 20))
    if kwargs.get('use_vwap', False):
        buy_conditions.append(df['Close'] > df['VWAP'])
    if kwargs.get('use_ma_cross', False):
        # Altın Kesişim (Golden Cross): Hızlı MA, yavaş MA'yı yukarı keser
        buy_conditions.append(
            (df['SMA_fast'] > df['SMA_slow']) & (df['SMA_fast_prev'] <= df['SMA_slow_prev'])
        )


    # Short (Sat) sinyali şartları
    if kwargs.get('use_rsi', False):
        sell_conditions.append(df['RSI'] > kwargs.get('rsi_sell', 70))
    if kwargs.get('use_macd', False):
        sell_conditions.append(df['MACD'] < df['MACD_signal'])
    if kwargs.get('use_bb', False):
        sell_conditions.append(df['Close'] > df['bb_hband'])
    if kwargs.get('use_adx', False):
        sell_conditions.append(df['ADX'] > kwargs.get('adx_threshold', 25))
    if kwargs.get('use_stoch', False):
        sell_conditions.append(df['Stoch_k'] > kwargs.get('stoch_sell_level', 80))
    if kwargs.get('use_vwap', False):
        sell_conditions.append(df['Close'] < df['VWAP'])
    if kwargs.get('use_ma_cross', False):
        # Ölüm Kesişimi (Death Cross): Hızlı MA, yavaş MA'yı aşağı keser
        sell_conditions.append(
            (df['SMA_fast'] < df['SMA_slow']) & (df['SMA_fast_prev'] >= df['SMA_slow_prev'])
        )


    # Koşulları birleştirme fonksiyonu
    def combine_conditions(conditions):
        if not conditions:
            return pd.Series([False] * len(df), index=df.index)
        if signal_mode == 'and':
            return pd.concat(conditions, axis=1).all(axis=1)
        else:  # or
            return pd.concat(conditions, axis=1).any(axis=1)

    # Al ve Sat sinyallerini üret
    df['Buy_Signal'] = combine_conditions(buy_conditions)
    df['Sell_Signal'] = combine_conditions(sell_conditions)

    # Ana 'Signal' sütununu üret
    df['Signal'] = 'Bekle'
    if signal_direction == 'Long':
        df.loc[df['Buy_Signal'], 'Signal'] = 'Al'
        df.loc[df['Sell_Signal'], 'Signal'] = 'Sat'  # Long pozisyonu kapama sinyali
    elif signal_direction == 'Short':
        df.loc[df['Sell_Signal'], 'Signal'] = 'Short'  # Yeni Short pozisyonu açma sinyali
        df.loc[df['Buy_Signal'], 'Signal'] = 'Al'  # Short pozisyonu kapama sinyali
    else:  # Both (Long & Short)
        df.loc[df['Buy_Signal'], 'Signal'] = 'Al'
        df.loc[df['Sell_Signal'], 'Signal'] = 'Short'

    print(f"📈 Standart Mod ({signal_mode.upper()}) - Ham Al Sinyali: {df['Buy_Signal'].sum()}")
    print(f"📉 Standart Mod ({signal_mode.upper()}) - Ham Sat/Short Sinyali: {df['Sell_Signal'].sum()}")

    return df


# --- Diğer Fonksiyonlar (Değişiklik Gerekmiyor) ---

def backtest_signals(df):
    trades = []
    position = None
    entry_price = 0
    entry_time = None

    for i in range(len(df)):
        signal = df['Signal'].iloc[i]
        price = df['Close'].iloc[i]
        time_idx = df.index[i]

        if position is None:
            if signal == 'Al':
                position = 'Long'
                entry_price = price
                entry_time = time_idx
            elif signal == 'Short':  # 'Sat' yerine 'Short' olarak değiştirildi
                position = 'Short'
                entry_price = price
                entry_time = time_idx

        elif position == 'Long':
            if signal == 'Sat' or signal == 'Short':  # Pozisyonu kapatmak için her iki sinyal de kullanılabilir
                exit_price = price
                ret = (exit_price - entry_price) / entry_price * 100
                trades.append({
                    'Pozisyon': 'Long', 'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                    'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': exit_price, 'Getiri (%)': round(ret, 2)
                })
                position = None

        elif position == 'Short':
            if signal == 'Al':
                exit_price = price
                ret = (entry_price - exit_price) / entry_price * 100
                trades.append({
                    'Pozisyon': 'Short', 'Giriş Zamanı': entry_time, 'Çıkış Zamanı': time_idx,
                    'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': exit_price, 'Getiri (%)': round(ret, 2)
                })
                position = None

    if position is not None:
        trades.append({
            'Pozisyon': position, 'Giriş Zamanı': entry_time, 'Çıkış Zamanı': pd.NaT,
            'Giriş Fiyatı': entry_price, 'Çıkış Fiyatı': np.nan, 'Getiri (%)': np.nan
        })

    return pd.DataFrame(trades)


def add_higher_timeframe_trend(df_lower, df_higher, trend_ema_period=50):
    """
    Üst zaman dilimindeki trendi hesaplar ve alt zaman dilimi verisine ekler.
    (KeyError'a karşı güçlendirilmiş versiyon)
    """
    # --- BAŞLANGIÇ: GÜVENLİK ÖNLEMİ ---
    # Eğer df_lower'da zaten bir 'Trend' sütunu varsa, birleştirmeden önce onu kaldır.
    # Bu, döngüsel çalışmalarda oluşabilecek MergeError'ı engeller.
    if 'Trend' in df_lower.columns:
        df_lower = df_lower.drop(columns=['Trend'])
    # --- BİTİŞ: GÜVENLİK ÖNLEMİ ---
    # Üst zaman dilimi verisine Trend_EMA ve Trend sütunlarını ekle
    df_higher['Trend_EMA'] = pd.Series.ewm(df_higher['Close'], span=trend_ema_period, adjust=False).mean()
    df_higher['Trend'] = np.where(df_higher['Close'] > df_higher['Trend_EMA'], 'Up', 'Down')
    df_trend = df_higher[['Trend']].copy()

    # İki zaman dilimini birleştir
    df_merged = pd.merge_asof(df_lower.sort_index(), df_trend.sort_index(),
                              left_index=True, right_index=True, direction='backward')

    # --- BAŞLANGIÇ: DÜZELTME ---
    # Eğer birleştirme sonrası 'Trend' sütunu oluşmadıysa (veri yetersizliği nedeniyle),
    # bu sütunu manuel olarak oluştur ve bilinen ilk değerle doldur.
    if 'Trend' not in df_merged.columns:
        # Geçici olarak boş bir Trend sütunu oluştur
        df_merged['Trend'] = np.nan
        # İlk geçerli trend değerini bul
        first_valid_trend = df_trend['Trend'].iloc[0]
        # Tüm boş değerleri bu ilk geçerli değerle doldur
        df_merged['Trend'].fillna(first_valid_trend, inplace=True)
    # --- BİTİŞ: DÜZELTME ---

    # Boşlukları ileriye doğru doldurarak sürekliliği sağla
    df_merged['Trend'] = df_merged['Trend'].ffill()

    return df_merged


def filter_signals_with_trend(df):
    """
    Mevcut sinyalleri üst zaman dilimi trendine göre filtreler.
    """
    # Trend "Up" iken "Short" sinyali gelirse, bunu "Bekle" olarak değiştir.
    df.loc[(df['Trend'] == 'Up') & (df['Signal'] == 'Short'), 'Signal'] = 'Bekle'

    # Trend "Down" iken "Al" sinyali gelirse, bunu "Bekle" olarak değiştir.
    df.loc[(df['Trend'] == 'Down') & (df['Signal'] == 'Al'), 'Signal'] = 'Bekle'

    print(f"📈 Trend Filtresi Sonrası Al Sinyali: {df[df['Signal'] == 'Al'].shape[0]}")
    print(f"📉 Trend Filtresi Sonrası Sat/Short Sinyali: {df[df['Signal'] == 'Short'].shape[0]}")

    return df