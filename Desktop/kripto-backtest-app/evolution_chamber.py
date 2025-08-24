# evolution_chamber.py

import random
import json
import time
import copy
from datetime import datetime

from database import (
    get_all_strategies,
    get_live_closed_trades_metrics,
    remove_strategy,
    add_or_update_strategy,
    update_strategy_status  # Bu satırı ekleyin
)

# --- Genetik Algoritma Parametreleri ---
# Popülasyonun ne kadarının eleneceğini belirler (en kötü %25)
ELIMINATION_RATE = 0.25
# Popülasyonun ne kadarının yeni nesil için ebeveyn olacağını belirler (en iyi %25)
SELECTION_RATE = 0.25
# Yeni oluşturulan stratejilerin ne kadarının mutasyonla oluşacağını belirler
MUTATION_CHANCE = 0.4  # %40 ihtimalle mutasyon, %60 ihtimalle çaprazlama


def crossover(parent1_params, parent2_params):
    """İki ebeveyn stratejisinin genlerini (parametrelerini) çaprazlar."""
    child_params = copy.deepcopy(parent1_params)

    # Hangi parametrelerin ikinci ebeveynden alınacağını rastgele seç
    keys_to_swap = random.sample(
        list(parent2_params.keys()),
        k=random.randint(1, len(parent2_params.keys()) // 2)
    )

    for key in keys_to_swap:
        if key in parent2_params:
            child_params[key] = parent2_params[key]

    print(f"    🧬 ÇAPRAZLAMA: '{', '.join(keys_to_swap)}' genleri ikinci ebeveynden alındı.")
    return child_params


def mutate(params):
    """Bir stratejinin genetiğini (parametrelerini) rastgele değiştirir."""
    mutated_params = copy.deepcopy(params)
    param_to_mutate = random.choice(list(mutated_params.keys()))

    # Değiştirilecek parametreye göre küçük bir oynama yap
    if isinstance(mutated_params[param_to_mutate], (int, float)):
        change_factor = 1 + random.uniform(-0.15, 0.15)  # +/- %15'lik değişim
        original_value = mutated_params[param_to_mutate]

        if isinstance(original_value, int):
            mutated_params[param_to_mutate] = max(1, int(original_value * change_factor))
        else:
            mutated_params[param_to_mutate] = max(0.1, float(original_value * change_factor))

        print(
            f"    🔬 MUTASYON: '{param_to_mutate}' parametresi {original_value:.2f} -> {mutated_params[param_to_mutate]:.2f} olarak değişti.")

    elif isinstance(mutated_params[param_to_mutate], bool):
        original_value = mutated_params[param_to_mutate]
        mutated_params[param_to_mutate] = not original_value
        print(
            f"    🔬 MUTASYON: '{param_to_mutate}' parametresi {original_value} -> {mutated_params[param_to_mutate]} olarak değişti.")

    return mutated_params


def run_evolution_cycle():
    """Tüm evrim döngüsünü çalıştıran ana fonksiyon."""
    print(f"\n--- 🧬 EVRİM DÖNGÜSÜ BAŞLATILDI ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ---")

    # 1. Stratejileri ve performanslarını al
    all_strategies = get_all_strategies()
    if len(all_strategies) < 4:
        print(
            "UYARI: Popülasyon çok küçük (4'ten az strateji var). Evrim döngüsü için yeterli çeşitlilik yok. Atlanıyor.")
        return {"status": "skipped", "reason": "Popülasyon çok küçük"}

    strategy_performance = []
    for strategy in all_strategies:
        metrics = get_live_closed_trades_metrics(strategy_id=strategy['id'])
        # Profit Factor'ü ana performans metriği olarak kullanalım. Sonsuz ise yüksek bir değer ata.
        performance_score = metrics.get('Profit Factor', 0)
        if performance_score == float('inf'):
            performance_score = 1000

        strategy_performance.append({
            "config": strategy,
            "score": performance_score,
            "trade_count": metrics.get("Toplam İşlem", 0)
        })

    # Sadece en az 3 işlem yapmış olanları dikkate alarak sırala, sonra skora göre
    strategy_performance.sort(key=lambda x: (x["trade_count"] > 2, x["score"]), reverse=True)

    print("\n--- PERFORMANS SIRALAMASI ---")
    for sp in strategy_performance:
        print(f"- '{sp['config']['name']}' | Skor (Profit Factor): {sp['score']:.2f} | İşlem: {sp['trade_count']}")

    # 2. En kötüleri ele, en iyileri seç
    population_size = len(strategy_performance)
    num_to_eliminate = int(population_size * ELIMINATION_RATE)
    num_to_select = int(population_size * SELECTION_RATE)

    if num_to_eliminate == 0 and population_size > 4:
        num_to_eliminate = 1  # Her döngüde en az bir stratejinin elendiğinden emin ol

    strategies_to_eliminate = strategy_performance[-num_to_eliminate:]
    parent_pool = strategy_performance[:num_to_select]

    if not parent_pool:
        print("UYARI: Hiç ebeveyn adayı bulunamadı (yeterli performansta strateji yok). Döngü sonlandırılıyor.")
        return {"status": "skipped", "reason": "Ebeveyn adayı yok"}

    # 3. Eleme
    print("\n--- ELEME AŞAMASI ---")
    eliminated_names = []
    for s_to_eliminate in strategies_to_eliminate:
        strategy_id = s_to_eliminate['config']['id']
        name = s_to_eliminate['config']['name']
        print(f"    - '{name}' (ID: {strategy_id}) düşük performans nedeniyle eleniyor.")
        update_strategy_status(strategy_id, 'paused')
        eliminated_names.append(name)

    # 4. Yeni Nesil Oluşturma
    print("\n--- YENİ NESİL ÜRETİMİ ---")
    new_strategy_count = len(strategies_to_eliminate)
    created_strategies = []
    for i in range(new_strategy_count):
        new_id = f"strategy_{int(time.time())}"

        # --- BAŞLANGIÇ: GÜVENLİK KONTROLÜ ---
        # Eğer çaprazlama için yeterli ebeveyn (en az 2) yoksa veya şans eseri mutasyon seçildiyse, mutasyon yap.
        if len(parent_pool) < 2 or random.random() < MUTATION_CHANCE:
            # Mutasyon
            parent = random.choice(parent_pool)
            new_params = mutate(parent['config']['strategy_params'])
            new_name = f"Mutant-{parent['config']['name'][:10]}-{i + 1}"
        else:
            # Çaprazlama
            parent1, parent2 = random.sample(parent_pool, 2)
            new_params = crossover(parent1['config']['strategy_params'], parent2['config']['strategy_params'])
            new_name = f"Çaprazlama-{parent1['config']['name'][:5]}/{parent2['config']['name'][:5]}-{i + 1}"
        # --- BİTİŞ: GÜVENLİK KONTROLÜ ---

        # Yeni strateji objesini oluştur
        new_strategy = {
            "id": new_id,
            "name": new_name,
            "status": "running",
            # Ebeveynlerin sembollerini ve zaman dilimini koru
            "symbols": parent_pool[0]['config']['symbols'],
            "interval": parent_pool[0]['config']['interval'],
            "strategy_params": new_params
        }

        add_or_update_strategy(new_strategy)
        print(f"    + YENİ STRATEJİ OLUŞTURULDU: '{new_name}' (ID: {new_id})")
        created_strategies.append(new_name)

    print("\n--- ✅ EVRİM DÖNGÜSÜ TAMAMLANDI ---\n")
    return {
        "status": "completed",
        "eliminated": eliminated_names,
        "created": created_strategies
    }


if __name__ == '__main__':
    # Bu dosyayı doğrudan çalıştırarak evrim döngüsünü test edebilirsiniz
    run_evolution_cycle()