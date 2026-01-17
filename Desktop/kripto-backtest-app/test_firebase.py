"""
Firebase bağlantısını test etmek için basit bir script
"""
import os
import sys

def test_firebase_connection():
    """Firebase bağlantısını test eder."""
    print("=" * 50)
    print("Firebase Bağlantı Testi")
    print("=" * 50)
    
    try:
        print("\n1. Firebase Admin SDK import ediliyor...")
        import firebase_admin
        from firebase_admin import credentials, firestore, storage
        print("   ✓ Firebase Admin SDK başarıyla import edildi")
        
        print("\n2. secrets.toml dosyası kontrol ediliyor...")
        script_dir = os.path.dirname(os.path.abspath(__file__))
        secrets_path = os.path.join(script_dir, '.streamlit', 'secrets.toml')
        
        if not os.path.exists(secrets_path):
            print(f"   ✗ secrets.toml dosyası bulunamadı: {secrets_path}")
            return False
        
        print(f"   ✓ secrets.toml dosyası bulundu: {secrets_path}")
        
        print("\n3. Firebase yapılandırması okunuyor...")
        import toml
        with open(secrets_path, 'r', encoding='utf-8') as f:
            secrets = toml.load(f)
        
        if 'firebase' not in secrets:
            print("   ✗ secrets.toml dosyasında 'firebase' bölümü bulunamadı")
            return False
        
        firebase_config = secrets['firebase']
        print("   ✓ Firebase yapılandırması okundu")
        
        print("\n4. Service account key dosyası kontrol ediliyor...")
        cred_path = firebase_config.get('credentials_path')
        if not cred_path or cred_path == "path/to/your/firebase-service-account-key.json":
            print("   ✗ credentials_path yapılandırılmamış veya varsayılan değerde")
            print("   Lütfen .streamlit/secrets.toml dosyasında credentials_path'i güncelleyin")
            return False
        
        if not os.path.exists(cred_path):
            print(f"   ✗ Service account key dosyası bulunamadı: {cred_path}")
            print("   Lütfen dosya yolunu kontrol edin")
            return False
        
        print(f"   ✓ Service account key dosyası bulundu: {cred_path}")
        
        print("\n5. Firebase Admin SDK başlatılıyor...")
        if firebase_admin._apps:
            print("   ⚠ Firebase zaten başlatılmış, yeniden başlatılıyor...")
            firebase_admin.delete_app(firebase_admin.get_app())
        
        cred = credentials.Certificate(cred_path)
        project_id = firebase_config.get('project_id')
        storage_bucket = firebase_config.get('storage_bucket')
        
        firebase_admin.initialize_app(cred, {
            'storageBucket': storage_bucket
        })
        print("   ✓ Firebase Admin SDK başarıyla başlatıldı")
        
        print("\n6. Firestore bağlantısı test ediliyor...")
        db = firestore.client()
        # Test koleksiyonuna bir test dokümanı yaz
        test_ref = db.collection('_test').document('connection_test')
        test_ref.set({'test': True, 'timestamp': firestore.SERVER_TIMESTAMP})
        print("   ✓ Firestore'a yazma başarılı")
        
        # Test dokümanını oku
        test_doc = test_ref.get()
        if test_doc.exists:
            print("   ✓ Firestore'dan okuma başarılı")
            # Test dokümanını sil
            test_ref.delete()
            print("   ✓ Test dokümanı temizlendi")
        
        print("\n7. Firebase Storage bağlantısı test ediliyor...")
        if storage_bucket:
            bucket = storage.bucket()
            print(f"   ✓ Storage bucket bağlantısı başarılı: {bucket.name}")
        else:
            print("   ⚠ Storage bucket yapılandırılmamış")
        
        print("\n" + "=" * 50)
        print("✓ TÜM TESTLER BAŞARILI!")
        print("=" * 50)
        print(f"\nProje ID: {project_id}")
        print(f"Storage Bucket: {storage_bucket}")
        print("\nFirebase kurulumu tamamlandı ve çalışıyor! 🎉")
        
        return True
        
    except ImportError as e:
        print(f"\n✗ HATA: Firebase paketleri kurulu değil: {e}")
        print("   Lütfen şu komutu çalıştırın: pip install firebase-admin google-cloud-storage")
        return False
    except FileNotFoundError as e:
        print(f"\n✗ HATA: Dosya bulunamadı: {e}")
        return False
    except Exception as e:
        print(f"\n✗ HATA: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_firebase_connection()
    sys.exit(0 if success else 1)

