# orchestrator.py (DNA havuzu zenginleştirilmiş ve karar mekanizması güncellenmiş nihai hali)

import time
import copy
import random

from database import get_all_strategies, add_or_update_strategy
from market_regime import get_market_regime


def get_strategy_dna(strategy_params):
    """
    Bir stratejinin parametrelerine bakarak onun 'DNA'sını veya karakterini belirler.
    Bu, stratejinin hangi piyasa koşulunda daha başarılı olabileceğine dair bir tahmindir.
    """
    dna = set()

    # --- TEMEL DNA'LAR ---
    if strategy_params.get('use_adx', False) and strategy_params.get('adx_threshold', 20) >= 22:
        dna.add("TREND TAKİPÇİSİ")

    if strategy_params.get('use_bb', False):
        dna.add("VOLATİLİTE ODAKLI")

    if strategy_params.get('use_rsi', False):
        if strategy_params.get('rsi_buy', 30) <= 30 and strategy_params.get('rsi_sell', 70) >= 70:
            dna.add("ORTALAMAYA DÖNÜŞ")

    # --- YENİ VE DETAYLI DNA'LAR ---
    if strategy_params.get('use_macd', False):
        dna.add("MOMENTUM ODAKLI")

    if strategy_params.get('signal_mode') == 'and':
        dna.add("TEYİT ODAKLI")
    else:
        dna.add("HIZLI SİNYAL")

    if strategy_params.get('use_mta', False):
        dna.add("TREND TEYİTLİ")

    if strategy_params.get('tp1_pct', 5.0) <= 2.0:  # TP1 hedefi %2'den küçükse
        dna.add("SCALPER (HIZLI KAZANÇ)")

    if not dna:
        dna.add("GENEL STRATEJİ")

    return list(dna)


def run_orchestrator_cycle():
    """
    Orkestratörün ana döngüsü. Piyasa rejimini analiz eder ve stratejileri
    bu rejime göre aktive veya deaktive eder.
    """
    print("\n--- 🤖 ORKESTRATÖR DÖNGÜSÜ BAŞLATILDI ---")

    market_regime = get_market_regime()
    if not market_regime:
        print("Orkestratör: Piyasa rejimi alınamadı, döngü atlanıyor.")
        return {"status": "skipped", "reason": "Piyasa rejimi alınamadı."}

    all_strategies = get_all_strategies()
    if not all_strategies:
        print("Orkestratör: Yönetilecek strateji bulunamadı.")
        return {"status": "skipped", "reason": "Yönetilecek strateji yok."}

    activated_strategies = []
    deactivated_strategies = []

    print("\n--- Strateji Değerlendirmesi ---")
    for strategy in all_strategies:
        strategy_params = strategy['strategy_params']
        dna = get_strategy_dna(strategy_params)
        is_suitable = False

        # --- YENİ VE GELİŞMİŞ KARAR VERME MANTIĞI ---
        trend = market_regime.get('trend_strength', '')
        volatility = market_regime.get('volatility', '')
        sentiment = market_regime.get('sentiment', '')

        # Güçlü trend piyasasında: Trend takipçileri ve teyitli stratejiler öncelikli
        if "GÜÇLÜ TREND" in trend:
            if "TREND TAKİPÇİSİ" in dna or "TREND TEYİTLİ" in dna or "MOMENTUM ODAKLI" in dna:
                is_suitable = True

        # Yüksek volatilitede: Hızlı tepki veren ve volatiliteyi kullananlar
        if "YÜKSEK VOLATİLİTE" in volatility:
            if "VOLATİLİTE ODAKLI" in dna or "HIZLI SİNYAL" in dna:
                is_suitable = True

        # Trendsiz piyasada: Yatay piyasa ve scalper'lar
        if "TRENDSİZ PİYASA" in trend:
            if "ORTALAMAYA DÖNÜŞ" in dna or "VOLATİLİTE ODAKLI" in dna or "SCALPER (HIZLI KAZANÇ)" in dna:
                is_suitable = True

        # Aşırı korku anlarında: Dipten alım yapabilecek stratejiler
        if "AŞIRI KORKU" in sentiment:
            if "ORTALAMAYA DÖNÜŞ" in dna and "TEYİT ODAKLI" in dna:  # Teyitli dipten alım
                is_suitable = True

        # Aşırı açgözlülükte: Hızlı kâr realize eden scalper'lar veya temkinli olanlar
        if "AŞIRI AÇGÖZLÜLÜK" in sentiment:
            if "SCALPER (HIZLI KAZANÇ)" in dna or "TEYİT ODAKLI" in dna:
                is_suitable = True

        # Her durumda çalışabilecek genel stratejiler
        if "GENEL STRATEJİ" in dna:
            is_suitable = True

        current_status = strategy.get('orchestrator_status', 'active')
        new_status = 'active' if is_suitable else 'inactive'

        if current_status != new_status:
            strategy['orchestrator_status'] = new_status
            add_or_update_strategy(strategy)

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