# Firebase Kurulum Adımları - Adım Adım Rehber

## Adım 1: Firebase Console'a Giriş Yapın

1. Tarayıcınızda şu adrese gidin: https://console.firebase.google.com/
2. Google hesabınızla giriş yapın

## Adım 2: Yeni Proje Oluşturun

1. Firebase Console'da **"Add project"** (Proje Ekle) butonuna tıklayın
2. **Proje adı** girin (örneğin: `kripto-backtest-app`)
3. **"Continue"** (Devam) butonuna tıklayın
4. Google Analytics'i isteğe bağlı olarak etkinleştirebilirsiniz (şimdilik atlayabilirsiniz)
5. **"Create project"** (Proje oluştur) butonuna tıklayın
6. Proje oluşturulmasını bekleyin (birkaç saniye sürebilir)
7. **"Continue"** butonuna tıklayın

## Adım 3: Firestore Database'i Etkinleştirin

1. Sol menüden **"Firestore Database"** seçeneğine tıklayın
2. **"Create database"** (Veritabanı oluştur) butonuna tıklayın
3. **"Start in test mode"** (Test modunda başlat) seçeneğini seçin
   - ⚠️ **Not:** Production için daha sonra güvenlik kuralları ayarlayacağız
4. **"Next"** (İleri) butonuna tıklayın
5. Bir **lokasyon** seçin (örneğin: `us-central1` veya size en yakın olanı)
6. **"Enable"** (Etkinleştir) butonuna tıklayın
7. Firestore Database oluşturulmasını bekleyin

## Adım 4: Firebase Storage'ı Etkinleştirin

1. Sol menüden **"Storage"** seçeneğine tıklayın
2. **"Get started"** (Başlayın) butonuna tıklayın
3. Güvenlik kurallarını onaylayın (test modu için "Start in test mode" seçin)
4. **"Next"** (İleri) butonuna tıklayın
5. Storage lokasyonunu seçin (Firestore ile aynı lokasyonu seçmeniz önerilir)
6. **"Done"** (Tamam) butonuna tıklayın

## Adım 5: Service Account Key Oluşturun

1. Firebase Console'da, sol üst köşedeki **⚙️ (Settings)** ikonuna tıklayın
2. **"Project settings"** (Proje ayarları) seçeneğini seçin
3. Üst menüden **"Service accounts"** (Hizmet hesapları) sekmesine tıklayın
4. **"Generate new private key"** (Yeni özel anahtar oluştur) butonuna tıklayın
5. Uyarı penceresinde **"Generate key"** (Anahtar oluştur) butonuna tıklayın
6. JSON dosyası otomatik olarak indirilecektir
7. Bu dosyayı güvenli bir yere kaydedin (örneğin: proje klasörünüze)

## Adım 6: Proje Bilgilerini Not Edin

Firebase Console'da şu bilgileri not edin:

1. **Project ID**: Proje ayarları sayfasında görünür (genellikle proje adıyla aynıdır)
2. **Storage Bucket**: Storage sayfasında görünür (genellikle: `your-project-id.appspot.com`)

## Adım 7: secrets.toml Dosyasını Yapılandırın

1. İndirdiğiniz JSON dosyasını proje klasörüne taşıyın (örneğin: `firebase-service-account-key.json`)
2. `.streamlit/secrets.toml` dosyasını düzenleyin ve şu bilgileri güncelleyin:

```toml
[firebase]
# Service account key dosyasının tam yolu
credentials_path = "C:/Users/Serce/Documents/GitHub/kripto-backtest-app/Desktop/kripto-backtest-app/firebase-service-account-key.json"

# Firebase proje bilgileri
project_id = "kripto-backtest-app"  # Buraya kendi proje ID'nizi yazın
storage_bucket = "kripto-backtest-app.appspot.com"  # Buraya kendi storage bucket adınızı yazın
```

**Önemli:** 
- Windows'ta dosya yolu için `\` yerine `/` kullanın veya `\\` şeklinde escape edin
- `project_id` ve `storage_bucket` değerlerini kendi Firebase projenizden alın

## Adım 8: Test Edin

Kurulumu test etmek için:

```python
from database import initialize_db
initialize_db()
```

Bu komut çalıştığında hata almazsanız, Firebase kurulumu başarılıdır!

## Sorun Giderme

### "Firebase başlatılamadı" hatası
- Service account key dosyasının yolunu kontrol edin
- Dosya yolunda Türkçe karakter olmamalı
- Windows'ta `\` yerine `/` veya `\\` kullanın

### "Permission denied" hatası
- Firestore güvenlik kurallarını kontrol edin
- Test modunda olduğundan emin olun

### "Storage bucket bulunamadı" hatası
- Storage bucket adını Firebase Console'dan kontrol edin
- Format: `your-project-id.appspot.com`

