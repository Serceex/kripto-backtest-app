# orchestrator.py

import time
import copy
import random

# Projemizin veritabanı fonksiyonlarını dahil ediyoruz
from database import get_all_strategies, add_or_update_strategy  # HATA DÜZELTMESİ: Bu satır güncellendi
from market_regime import get_market_regime


def get_strategy_dna(strategy_params):
    """
    Bir stratejinin parametrelerine bakarak onun 'DNA'sını veya karakterini belirler.
    Bu, stratejinin hangi piyasa koşulunda daha başarılı olabileceğine dair bir tahmindir.
    """
    dna = set()

    # 1. Trend Karakteri
    if strategy_params.get('use_adx', False) and strategy_params.get('adx_threshold', 20) >= 22:
        dna.add("TREND_RIDER")  # Trend takipçisi

    # 2. Volatilite/Yatay Piyasa Karakteri
    if strategy_params.get('use_bb', False):
        dna.add("VOLATILITY_TRADER")  # Bollinger bandı kullananlar yatay/volatil piyasaları sever

    # 3. Aşırı Alım/Satım (Mean Reversion) Karakteri
    if strategy_params.get('use_rsi', False):
        if strategy_params.get('rsi_buy', 30) <= 30 and strategy_params.get('rsi_sell', 70) >= 70:
            dna.add("MEAN_REVERSION")  # Düşükten alıp yüksekten satmaya odaklı

    # Eğer hiçbir belirgin özellik yoksa, genel bir etiket ver
    if not dna:
        dna.add("GENERALIST")

    return list(dna)


def run_orchestrator_cycle():
    """
    Orkestratörün ana döngüsü. Piyasa rejimini analiz eder ve stratejileri
    bu rejime göre aktive veya deaktive eder.
    """
    print("\n--- 🤖 ORKESTRATÖR DÖNGÜSÜ BAŞLATILDI ---")

    # 1. Mevcut Piyasa Rejimini Al
    market_regime = get_market_regime()
    if not market_regime:
        print("Orkestratör: Piyasa rejimi alınamadı, döngü atlanıyor.")
        return {"status": "skipped", "reason": "Piyasa rejimi alınamadı."}

    # 2. Tüm Stratejileri Al
    all_strategies = get_all_strategies()
    if not all_strategies:
        print("Orkestratör: Yönetilecek strateji bulunamadı.")
        return {"status": "skipped", "reason": "Yönetilecek strateji yok."}

    activated_strategies = []
    deactivated_strategies = []

    # 3. Her Stratejiyi Değerlendir ve Karar Ver
    print("\n--- Strateji Değerlendirmesi ---")
    for strategy in all_strategies:
        strategy_params = strategy['strategy_params']
        dna = get_strategy_dna(strategy_params)

        is_suitable = False  # Strateji mevcut rejime uygun mu?

        # --- KARAR VERME MANTIĞI ---
        # Bu mantık zamanla daha da karmaşık hale getirilebilir.

        # Güçlü trend piyasasında, trend takipçisi stratejileri aktive et
        if "GÜÇLÜ TREND" in market_regime.get('trend_strength', ''):
            if "TREND_RIDER" in dna or "GENERALIST" in dna:
                is_suitable = True

        # Yüksek volatilitede, volatilite stratejilerini aktive et
        if "YÜKSEK VOLATİLİTE" in market_regime.get('volatility', ''):
            if "VOLATILITY_TRADER" in dna or "GENERALIST" in dna:
                is_suitable = True

        # Trendsiz piyasada, yatay piyasa (mean reversion) stratejilerini aktive et
        if "TRENDSİZ PİYASA" in market_regime.get('trend_strength', ''):
            if "MEAN_REVERSION" in dna or "VOLATILITY_TRADER" in dna or "GENERALIST" in dna:
                is_suitable = True

        # Aşırı korku anlarında, dipten alım yapabilecek (mean reversion) stratejileri aktive et
        if "AŞIRI KORKU" in market_regime.get('sentiment', ''):
            if "MEAN_REVERSION" in dna:
                is_suitable = True

        # Kararı veritabanına işle
        current_status = strategy.get('orchestrator_status', 'active')
        new_status = 'active' if is_suitable else 'inactive'

        if current_status != new_status:
            strategy['orchestrator_status'] = new_status
            add_or_update_strategy(strategy)  # Stratejinin tamamını güncelliyoruz

            if new_status == 'active':
                activated_strategies.append(strategy['name'])
                print(f"✅ AKTİVE EDİLDİ: '{strategy['name']}' (DNA: {dna}) -> Mevcut rejime uygun.")
            else:
                deactivated_strategies.append(strategy['name'])
                print(f"⏸️ YEDEĞE ALINDI: '{strategy['name']}' (DNA: {dna}) -> Mevcut rejime uygun değil.")
        else:
            print(f"🔄 DURUM KORUNDU: '{strategy['name']}' -> '{current_status}' (DNA: {dna})")

    print("\n--- 🤖 ORKESTRATÖR DÖNGÜSÜ TAMAMLANDI ---")
    return {
        "status": "completed",
        "market_regime": market_regime,
        "activated": activated_strategies,
        "deactivated": deactivated_strategies
    }


if __name__ == '__main__':
    run_orchestrator_cycle()
