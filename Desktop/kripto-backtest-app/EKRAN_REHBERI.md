# 📱 Veritas Point Labs - Ekran Rehberi

## 🏠 Ana Sayfa Seçimi

Sol kenar çubukta iki ana sayfa bulunur:

### 1. 🧪 Deney Odası
**Amaç:** Stratejileri test etmek, optimize etmek ve grafik analizi yapmak

### 2. 🔬 Kontrol Merkezi  
**Amaç:** Canlı stratejileri yönetmek, izlemek ve kontrol etmek (Şifre gerekli)

---

## 🧪 DENEY ODASI

### 📊 Backtest Sonuçları Sekmesi

**Ne İşe Yarar:**
- Seçtiğiniz semboller ve zaman diliminde stratejinizi test eder
- Geçmiş veriler üzerinde stratejinin nasıl performans gösterdiğini gösterir
- Detaylı performans metrikleri sunar

**Özellikler:**
- **Portföy Backtest Başlat** butonu ile test başlatılır
- Toplam işlem sayısı, kazançlı işlem oranı, toplam getiri gösterilir
- Sharpe Oranı, Sortino Oranı, Calmar Oranı gibi risk metrikleri hesaplanır
- Maksimum düşüş (Drawdown) analizi yapılır
- Sermaye eğrisi ve düşüş grafiği gösterilir
- Tüm işlemlerin detaylı listesi görüntülenir

**Kullanım:**
1. Kenar çubuktan semboller ve zaman dilimi seçin
2. Strateji parametrelerini ayarlayın
3. "Portföy Backtest Başlat" butonuna tıklayın
4. Sonuçları inceleyin

---

### 📈 Grafik Analizi Sekmesi

**Ne İşe Yarar:**
- Backtest sonuçlarını sembol bazında detaylı grafiklerle gösterir
- Teknik göstergeleri görselleştirir
- Alım/satım sinyallerini grafik üzerinde işaretler

**Özellikler:**
- Mum grafikleri (Candlestick)
- SMA, EMA, Bollinger Bands, RSI, MACD, ADX, VWAP, Stochastic gibi göstergeler
- Fibonacci seviyeleri
- Alım/satım sinyalleri grafik üzerinde işaretlenir
- Zoom, pan gibi interaktif özellikler

**Kullanım:**
1. Önce "Backtest Sonuçları" sekmesinden bir test çalıştırın
2. Bu sekmede analiz edilecek sembolü seçin
3. Kenar çubuktan gösterilecek göstergeleri seçin
4. Grafik üzerinde sinyalleri inceleyin

---

### ⚙️ Strateji Optimizasyonu Sekmesi

**Ne İşe Yarar:**
- Strateji parametrelerinin binlerce kombinasyonunu test eder
- En iyi performans gösteren parametreleri bulur
- Otomatik optimizasyon yapar

**Özellikler:**
- Optimizasyon hedefi seçimi (Sharpe, Sortino, Calmar, Getiri, Drawdown)
- Parametre test aralıkları belirleme
- RSI, MACD, Bollinger Bands gibi göstergelerin parametrelerini optimize eder
- Sonuçları tablo ve grafik olarak gösterir
- En iyi parametreleri otomatik önerir

**Kullanım:**
1. Optimizasyon hedefini seçin (örn: Sharpe Oranı)
2. Test edilecek parametrelerin aralıklarını belirleyin
3. "Optimizasyonu Başlat" butonuna tıklayın
4. Sonuçları inceleyin ve en iyi parametreleri kullanın

---

## 🔬 KONTROL MERKEZİ (Şifre Gerekli)

### 📈 Genel Bakış Sekmesi

**Ne İşe Yarar:**
- Tüm canlı stratejilerin genel durumunu gösterir
- Global piyasa durumunu takip eder
- Portföy performansını özetler

**Özellikler:**
- **Global Piyasa Durumu:**
  - Korku ve Hırs Endeksi (Fear & Greed Index)
  - Bitcoin Dominansı
  
- **Genel Portföy Durumu:**
  - Açık pozisyonların toplam kâr/zararı
  - Genel başarı oranı
  - En kârlı strateji
  - Strateji bazında kâr dağılımı grafiği

**Kullanım:**
- Otomatik olarak güncellenir
- Tüm stratejilerin durumunu tek bakışta görürsünüz

---

### ⚙️ Strateji Yönetimi Sekmesi

**Ne İşe Yarar:**
- Canlı stratejileri oluşturur, düzenler ve yönetir
- Strateji parametrelerini ayarlar
- RL (Reinforcement Learning) ajanları atar

**Özellikler:**

**Yeni Strateji Ekleme:**
- Strateji adı belirleme
- RL Ajanı seçimi (opsiyonel)
- Sembol ve zaman dilimi ayarları
- Stratejiyi canlı izlemeye alma

**Mevcut Stratejileri Yönetme:**
- Her strateji için performans metrikleri (Profit Factor, Getiri, Başarı Oranı)
- **Strateji Kontrolleri:**
  - ⏸️ Durdur / ▶️ Devam Et
  - 🗑️ Sil
  - ⚙️ Ayarları Tam Düzenle
  - 📥 Ayarları Kenar Çubuğuna Yükle

- **Canlı İşlem Parametreleri:**
  - Marjin Tipi (ISOLATED/CROSSED)
  - Kaldıraç (1-50x)
  - İşlem Tutarı ($)
  - Borsada İşlem (Aktif/Pasif)
  - Telegram Bildirim (Evet/Hayır)

**Kullanım:**
1. Yeni strateji eklemek için "➕ Yeni Canlı İzleme Stratejisi Ekle" expander'ını açın
2. Strateji adını girin ve ayarları yapın
3. Mevcut stratejileri düzenlemek için expander'ları açın
4. Parametreleri değiştirin, durdur/başlat butonlarını kullanın

---

### 🤖 Strateji Koçu Sekmesi

**Ne İşe Yarar:**
- Piyasa rejimini (market regime) analiz eder
- Piyasa koşullarına göre stratejileri otomatik aktive/deaktive eder
- Akıllı strateji yönetimi yapar

**Özellikler:**
- Orkestratör döngüsü çalıştırma
- Piyasa rejimi tespiti (Trend, Range, Volatile)
- Strateji DNA'larını görüntüleme
- Otomatik strateji aktivasyon/deaktivasyon

**Kullanım:**
1. "🔄 Orkestratör Döngüsünü Çalıştır" butonuna tıklayın
2. Piyasa rejimi analiz edilir
3. Uygun stratejiler aktive, uygun olmayanlar deaktive edilir

---

### 📊 Açık Pozisyonlar Sekmesi

**Ne İşe Yarar:**
- Tüm açık pozisyonları listeler
- Anlık kâr/zarar durumunu gösterir
- Pozisyon detaylarını görüntüler

**Özellikler:**
- Strateji adı, sembol, pozisyon tipi (Long/Short)
- Giriş fiyatı, stop loss, take profit seviyeleri
- Anlık kâr/zarar yüzdesi
- Manuel işlem yapma (Kapat, Stop Loss Güncelle)

**Kullanım:**
- Otomatik olarak güncellenir
- Pozisyonları takip edin ve gerekirse manuel müdahale edin

---

### 🔔 Alarm Geçmişi Sekmesi

**Ne İşe Yarar:**
- Tüm sinyal ve alarm geçmişini gösterir
- Strateji bazında alarm filtreleme
- Zaman bazında sıralama

**Özellikler:**
- Zaman, sembol, sinyal tipi, fiyat bilgisi
- Strateji bazında filtreleme
- Son 50 alarm gösterimi
- Tablo formatında görüntüleme

**Kullanım:**
- Otomatik olarak güncellenir
- Geçmiş sinyalleri inceleyin ve strateji performansını değerlendirin

---

### 🧬 Gen Havuzu Sekmesi

**Ne İşe Yarar:**
- Evrimsel algoritma ile strateji optimizasyonu
- Genetik algoritma kullanarak en iyi strateji kombinasyonlarını bulur
- Strateji DNA'larını evrimleştirir

**Özellikler:**
- Evrim döngüsü çalıştırma
- Popülasyon yönetimi
- Mutasyon ve crossover işlemleri
- En iyi strateji kombinasyonlarını bulma

**Kullanım:**
1. "🧬 Evrim Döngüsünü Başlat" butonuna tıklayın
2. Sistem otomatik olarak en iyi strateji kombinasyonlarını bulur
3. Sonuçları inceleyin

---

### 🤖 RL Ajan Sekmesi

**Ne İşe Yarar:**
- Reinforcement Learning (Pekiştirmeli Öğrenme) ajanları eğitir
- Eğitilmiş modelleri yönetir
- RL ajanları ile backtest yapar

**Özellikler:**

**Model Eğitimi:**
- Sembol, zaman dilimi, eğitim adımı sayısı seçimi
- PPO (Proximal Policy Optimization) algoritması
- TensorBoard logları
- Model kaydetme

**Model Yönetimi:**
- Eğitilmiş modellerin listesi
- Model silme
- Model detayları

**Backtest:**
- Eğitilmiş model ile backtest yapma
- RL sinyallerini görüntüleme
- Performans metrikleri

**Kullanım:**
1. Model eğitmek için parametreleri ayarlayın ve "Eğitimi Başlat" butonuna tıklayın
2. Eğitilmiş modelleri "Model Yönetimi" bölümünden görüntüleyin
3. Backtest yapmak için model seçin ve "Backtest Başlat" butonuna tıklayın

---

## 📋 Kenar Çubuk (Sidebar) Özellikleri

### 📊 Grafik Gösterge Seçenekleri
- SMA, EMA, Bollinger Bands, VWAP, ADX, Stochastic, Fibonacci seviyeleri
- Grafik üzerinde hangi göstergelerin görüneceğini kontrol eder

### ⏳ Çoklu Zaman Dilimi Analizi (MTA)
- Daha yüksek zaman diliminde trend analizi
- Trend EMA periyodu ayarlama
- Trend filtresi aktif/pasif

### 🔧 Diğer Parametreler
- Sinyal kriterleri (RSI, MACD, Bollinger, ADX)
- Stop Loss ve Take Profit ayarları
- Cooldown (soğuma) süresi
- Komisyon oranı

---

## 🎯 Genel Kullanım Akışı

### 1. Strateji Test Etme (Deney Odası)
1. Kenar çubuktan sembol ve zaman dilimi seçin
2. Strateji parametrelerini ayarlayın
3. "Portföy Backtest Başlat" butonuna tıklayın
4. Sonuçları "Backtest Sonuçları" sekmesinde inceleyin
5. "Grafik Analizi" sekmesinde detaylı grafikleri görün
6. "Strateji Optimizasyonu" ile en iyi parametreleri bulun

### 2. Canlı Strateji Yönetimi (Kontrol Merkezi)
1. Şifre ile giriş yapın
2. "Strateji Yönetimi" sekmesinden yeni strateji ekleyin
3. Strateji parametrelerini ayarlayın
4. "Genel Bakış" sekmesinden tüm stratejileri izleyin
5. "Açık Pozisyonlar" sekmesinden pozisyonları takip edin
6. "Alarm Geçmişi" sekmesinden sinyalleri inceleyin

### 3. Gelişmiş Özellikler
1. "Strateji Koçu" ile otomatik strateji yönetimi
2. "Gen Havuzu" ile evrimsel optimizasyon
3. "RL Ajan" ile yapay zeka destekli trading

---

## 💡 İpuçları

- **Backtest yapmadan önce:** Kenar çubuktan tüm parametreleri kontrol edin
- **Canlı trading için:** Önce backtest yapın, sonra canlıya alın
- **RL Ajan kullanımı:** Model eğitimi zaman alabilir, sabırlı olun
- **Optimizasyon:** Çok fazla parametre optimize etmek uzun sürebilir
- **Telegram bildirimleri:** secrets.toml dosyasında Telegram ayarlarını yapın

---

## 🔐 Güvenlik

- Kontrol Merkezi şifre korumalıdır
- Şifre `.streamlit/secrets.toml` dosyasında `app.password` olarak ayarlanır
- Canlı trading için "Borsada İşlem" seçeneğini dikkatli kullanın

---

**Sorularınız için:** Uygulama içindeki bilgi mesajlarını ve tooltip'leri okuyun.

