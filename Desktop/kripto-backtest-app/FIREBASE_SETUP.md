# Firebase Kurulum Rehberi

Bu proje artık PostgreSQL yerine Firebase Firestore kullanmaktadır. Kurulum adımları:

## 1. Firebase Projesi Oluşturma

1. [Firebase Console](https://console.firebase.google.com/) adresine gidin
2. "Add project" (Proje Ekle) butonuna tıklayın
3. Proje adını girin ve gerekli adımları tamamlayın
4. Proje oluşturulduktan sonra, sol menüden **Firestore Database**'i seçin
5. "Create database" (Veritabanı oluştur) butonuna tıklayın
6. **Test mode** (Test modu) seçeneğini seçin (geliştirme için) veya production kuralları ayarlayın
7. Bir lokasyon seçin (örneğin: `us-central1`)

## 2. Firebase Storage Kurulumu (RL Modelleri için)

1. Firebase Console'da sol menüden **Storage**'ı seçin
2. "Get started" (Başlayın) butonuna tıklayın
3. Güvenlik kurallarını onaylayın
4. Storage bucket'ı oluşturun

## 3. Service Account Key Oluşturma

1. Firebase Console'da, sol üst köşedeki ⚙️ (Settings) ikonuna tıklayın
2. "Project settings" (Proje ayarları) seçeneğini seçin
3. "Service accounts" (Hizmet hesapları) sekmesine gidin
4. "Generate new private key" (Yeni özel anahtar oluştur) butonuna tıklayın
5. JSON dosyasını güvenli bir yere kaydedin (örneğin: `firebase-service-account-key.json`)

## 4. Yapılandırma

`.streamlit/secrets.toml` dosyasını düzenleyin:

```toml
[firebase]
# Service account key dosyasının tam yolu
credentials_path = "C:/path/to/your/firebase-service-account-key.json"

# Firebase proje bilgileri (service account key dosyasında da bulunur)
project_id = "your-firebase-project-id"
storage_bucket = "your-firebase-project-id.appspot.com"
```

**Alternatif:** Service account key JSON içeriğini direkt olarak da ekleyebilirsiniz:

```toml
[firebase]
credentials_json = {
    "type": "service_account",
    "project_id": "your-project-id",
    "private_key_id": "...",
    "private_key": "...",
    "client_email": "...",
    ...
}
project_id = "your-firebase-project-id"
storage_bucket = "your-firebase-project-id.appspot.com"
```

## 5. Bağımlılıkları Kurma

```bash
pip install -r requirements.txt
```

Bu komut `firebase-admin` ve `google-cloud-storage` paketlerini kuracaktır.

## 6. Güvenlik Kuralları (Firestore)

Geliştirme için test modu kullanabilirsiniz, ancak production için güvenlik kuralları ayarlayın:

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if request.auth != null; // Sadece authenticated kullanıcılar
      // veya
      // allow read, write: if true; // Herkese açık (sadece test için)
    }
  }
}
```

## 7. Veri Yapısı

Firestore'da otomatik olarak şu koleksiyonlar oluşturulacak:

- **strategies**: Strateji bilgileri
- **positions**: Pozisyon bilgileri
- **alarms**: Alarm/sinyal geçmişi
- **manual_actions**: Manuel işlemler
- **rl_models**: RL model metadata (dosyalar Storage'da)

## Notlar

- Firebase Firestore NoSQL bir veritabanıdır, SQL sorguları yerine Firestore query'leri kullanılır
- Binary dosyalar (RL modelleri) Firebase Storage'da saklanır
- Firestore otomatik olarak koleksiyonları oluşturur, `initialize_db()` fonksiyonu sadece kontrol amaçlıdır
- Tarih/saat alanları için `firestore.SERVER_TIMESTAMP` kullanılır

## Sorun Giderme

- **"Firebase başlatılamadı" hatası**: Service account key dosyasının yolunu ve içeriğini kontrol edin
- **"Permission denied" hatası**: Firestore güvenlik kurallarını kontrol edin
- **"Storage bucket bulunamadı" hatası**: Storage bucket adını ve Firebase Console'daki ayarları kontrol edin

