# database.py (Firebase Firestore Uyumlu)

import firebase_admin
from firebase_admin import credentials, firestore, storage
import pandas as pd
import json
import os
from datetime import datetime
import numpy as np
import toml
import io
import streamlit as st
from typing import Optional, Dict, List, Any

# Firebase bağlantısı
_db = None
_bucket = None

def initialize_firebase():
    """Firebase Admin SDK'yı başlatır. Storage opsiyoneldir."""
    global _db, _bucket
    
    if _db is not None:
        return _db, _bucket
    
    try:
        # Streamlit secrets'tan Firebase yapılandırmasını al
        try:
            import streamlit as st
            firebase_config = st.secrets["firebase"]
            cred_path = firebase_config.get("credentials_path")
            project_id = firebase_config.get("project_id")
            storage_bucket = firebase_config.get("storage_bucket")
        except:
            # .streamlit/secrets.toml dosyasından oku
            script_dir = os.path.dirname(os.path.abspath(__file__))
            secrets_path = os.path.join(script_dir, '.streamlit', 'secrets.toml')
            with open(secrets_path, 'r', encoding='utf-8') as f:
                secrets = toml.load(f)
            firebase_config = secrets["firebase"]
            cred_path = firebase_config.get("credentials_path")
            project_id = firebase_config.get("project_id")
            storage_bucket = firebase_config.get("storage_bucket")
        
        # Firebase Admin SDK'yı başlat
        if not firebase_admin._apps:
            if cred_path and os.path.exists(cred_path):
                cred = credentials.Certificate(cred_path)
                # Storage bucket opsiyonel, yoksa None olarak bırak
                app_options = {}
                if storage_bucket:
                    app_options['storageBucket'] = storage_bucket
                firebase_admin.initialize_app(cred, app_options)
            elif project_id:
                # Service account key JSON string olarak da verilebilir
                cred_json = firebase_config.get("credentials_json")
                if cred_json:
                    import tempfile
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
                        f.write(json.dumps(cred_json))
                        cred_path = f.name
                    cred = credentials.Certificate(cred_path)
                    app_options = {}
                    if storage_bucket:
                        app_options['storageBucket'] = storage_bucket
                    firebase_admin.initialize_app(cred, app_options)
                else:
                    # Default credentials kullan (örneğin GOOGLE_APPLICATION_CREDENTIALS env var)
                    app_options = {'projectId': project_id}
                    if storage_bucket:
                        app_options['storageBucket'] = storage_bucket
                    firebase_admin.initialize_app(options=app_options)
            else:
                raise Exception("Firebase yapılandırması bulunamadı")
        
        _db = firestore.client()
        # Storage bucket opsiyonel, yoksa None döndür
        _bucket = storage.bucket() if storage_bucket else None
        if _bucket:
            print("--- [DEBUG] Firebase başarıyla başlatıldı (Firestore + Storage).")
        else:
            print("--- [DEBUG] Firebase başarıyla başlatıldı (Firestore - Storage kullanılmıyor).")
        return _db, _bucket
        
    except Exception as e:
        print(f"--- [KRİTİK HATA] Firebase başlatılamadı: {e} ---")
        try:
            import streamlit as st
            st.error(f"FIREBASE BAĞLANTI HATASI: {e}")
            st.info("Lütfen .streamlit/secrets.toml dosyanızdaki Firebase yapılandırmasını kontrol edin.")
        except:
            pass
        return None, None

def get_db():
    """Firestore veritabanı bağlantısını döndürür."""
    db, _ = initialize_firebase()
    return db

def get_storage_bucket():
    """Firebase Storage bucket'ını döndürür."""
    _, bucket = initialize_firebase()
    return bucket

def initialize_db():
    """Veritabanı koleksiyonlarını başlatır (Firestore otomatik oluşturur, bu fonksiyon sadece kontrol için)."""
    print("--- [DEBUG] initialize_db fonksiyonu çağrıldı.")
    try:
        db = get_db()
        if db is None:
            raise Exception("Firebase bağlantısı yok.")
        
        # Firestore'da koleksiyonlar otomatik oluşturulur, bu yüzden sadece test ediyoruz
        test_ref = db.collection('strategies').limit(1)
        list(test_ref.stream())
        
        print("--- [DATABASE] Firebase Firestore başarıyla başlatıldı/doğrulandı. ---")
    except Exception as e:
        print(f"--- [KRİTİK HATA] Veritabanı başlatılamadı: {e} ---")

def save_rl_model(name, description, model_buffer):
    """Eğitilmiş bir RL modelini Firebase Storage'a veya yerel dosya sistemine kaydeder."""
    try:
        db = get_db()
        bucket = get_storage_bucket()
        storage_path = None
        storage_type = None
        
        # Önce Firebase Storage'ı dene
        if bucket is not None:
            try:
                blob = bucket.blob(f"rl_models/{name}.zip")
                model_buffer.seek(0)  # Buffer'ı başa al
                blob.upload_from_file(model_buffer, content_type='application/zip')
                storage_path = f"rl_models/{name}.zip"
                storage_type = "firebase_storage"
                print(f"--- [DATABASE] RL Modeli Firebase Storage'a kaydedildi: {storage_path}")
            except Exception as storage_error:
                print(f"--- [UYARI] Firebase Storage'a kaydedilemedi, yerel dosya sistemine kaydediliyor: {storage_error}")
                bucket = None  # Storage kullanılamıyor, yerel dosya sistemine geç
        
        # Firebase Storage yoksa veya başarısız olduysa yerel dosya sistemine kaydet
        if bucket is None:
            # Yerel models klasörünü oluştur
            script_dir = os.path.dirname(os.path.abspath(__file__))
            models_dir = os.path.join(script_dir, 'rl_models_local')
            os.makedirs(models_dir, exist_ok=True)
            
            # Model dosyasını yerel olarak kaydet
            local_path = os.path.join(models_dir, f"{name}.zip")
            model_buffer.seek(0)  # Buffer'ı başa al
            with open(local_path, 'wb') as f:
                f.write(model_buffer.read())
            
            storage_path = local_path
            storage_type = "local_file"
            print(f"--- [DATABASE] RL Modeli yerel dosya sistemine kaydedildi: {storage_path}")
        
        # Firestore'da model metadata'sını kaydet
        model_ref = db.collection('rl_models').document(name)
        model_ref.set({
            'name': name,
            'description': description,
            'storage_path': storage_path,
            'storage_type': storage_type,
            'created_at': firestore.SERVER_TIMESTAMP
        }, merge=True)
        
        print(f"--- [DATABASE] RL Modeli '{name}' başarıyla kaydedildi/güncellendi. ---")
    except Exception as e:
        print(f"--- [HATA] RL Modeli kaydedilemedi: {e} ---")
        raise

def get_rl_model_by_id(model_id):
    """Bir RL modelini ID'sine göre Firebase Storage'dan veya yerel dosya sisteminden çeker."""
    try:
        db = get_db()
        
        # Önce Firestore'dan model bilgisini al
        model_ref = db.collection('rl_models').document(str(model_id))
        model_doc = model_ref.get()
        
        if not model_doc.exists:
            # ID ile değil, name ile arama yap
            models = db.collection('rl_models').where('name', '==', str(model_id)).limit(1).stream()
            model_doc = next(models, None)
            if not model_doc:
                return None
        
        model_data = model_doc.to_dict()
        storage_path = model_data.get('storage_path')
        storage_type = model_data.get('storage_type', 'firebase_storage')
        
        if not storage_path:
            return None
        
        model_buffer = io.BytesIO()
        
        # Storage tipine göre modeli yükle
        if storage_type == 'firebase_storage':
            bucket = get_storage_bucket()
            if bucket is None:
                print("--- [UYARI] Firebase Storage kullanılamıyor, yerel dosya sisteminden yükleniyor...")
                # Yerel dosya sistemine fallback
                if os.path.exists(storage_path):
                    with open(storage_path, 'rb') as f:
                        model_buffer.write(f.read())
                    model_buffer.seek(0)
                    return model_buffer
                return None
            
            blob = bucket.blob(storage_path)
            blob.download_to_file(model_buffer)
            model_buffer.seek(0)
        elif storage_type == 'local_file':
            # Yerel dosya sisteminden yükle
            if os.path.exists(storage_path):
                with open(storage_path, 'rb') as f:
                    model_buffer.write(f.read())
                model_buffer.seek(0)
            else:
                print(f"--- [HATA] Yerel model dosyası bulunamadı: {storage_path}")
                return None
        else:
            # Eski format için fallback (storage_type belirtilmemiş)
            bucket = get_storage_bucket()
            if bucket:
                try:
                    blob = bucket.blob(storage_path)
                    blob.download_to_file(model_buffer)
                    model_buffer.seek(0)
                except:
                    # Storage başarısız olursa yerel dosyayı dene
                    if os.path.exists(storage_path):
                        with open(storage_path, 'rb') as f:
                            model_buffer.write(f.read())
                        model_buffer.seek(0)
                    else:
                        return None
            else:
                # Yerel dosyayı dene
                if os.path.exists(storage_path):
                    with open(storage_path, 'rb') as f:
                        model_buffer.write(f.read())
                    model_buffer.seek(0)
                else:
                    return None
        
        return model_buffer
    except Exception as e:
        print(f"--- [HATA] RL Modeli alınamadı: {e} ---")
        return None

@st.cache_data(ttl=15)
def get_all_rl_models_info():
    """Tüm RL modellerinin bilgilerini (ID ve İsim) listeler."""
    try:
        db = get_db()
        models_ref = db.collection('rl_models').order_by('created_at', direction=firestore.Query.DESCENDING).stream()
        
        result = []
        for doc in models_ref:
            data = doc.to_dict()
            result.append({
                'id': doc.id,
                'name': data.get('name', doc.id),
                'description': data.get('description', ''),
                'created_at': data.get('created_at')
            })
        return result
    except Exception as e:
        print(f"--- [HATA] RL Modelleri listelenemedi: {e} ---")
        return []

def add_or_update_strategy(strategy_config):
    """
    Bir stratejiyi ekler veya günceller. Güncelleme sırasında, stratejiden
    kaldırılan sembollerin eski pozisyon kayıtlarını otomatik olarak temizler.
    """
    try:
        db = get_db()
        strategy_id = strategy_config.get('id')
        new_symbols = set(strategy_config.get("symbols", []))
        
        # Mevcut stratejiyi kontrol et
        strategy_ref = db.collection('strategies').document(strategy_id)
        strategy_doc = strategy_ref.get()
        
        if strategy_doc.exists:
            current_data = strategy_doc.to_dict()
            current_symbols = set(current_data.get('symbols', []))
            removed_symbols = current_symbols - new_symbols
            
            if removed_symbols:
                print(f"--- [DATABASE] Temizlik: Strateji '{strategy_id}' için kaldırılan semboller tespit edildi: {removed_symbols}")
                # Kaldırılan semboller için pozisyonları sil
                positions_ref = db.collection('positions')
                for symbol_to_remove in removed_symbols:
                    positions_query = positions_ref.where('strategy_id', '==', strategy_id).where('symbol', '==', symbol_to_remove).stream()
                    for pos_doc in positions_query:
                        pos_doc.reference.delete()
                print(f"--- [DATABASE] '{strategy_id}' için eski pozisyon kayıtları temizlendi.")
        
        # Stratejiyi ekle veya güncelle
        rl_model_id = strategy_config.get('rl_model_id')
        if rl_model_id is not None:
            try:
                rl_model_id = int(rl_model_id)
            except (ValueError, TypeError):
                rl_model_id = None
        
        strategy_data = {
            'id': strategy_id,
            'name': strategy_config.get('name'),
            'status': strategy_config.get('status', 'running'),
            'symbols': strategy_config.get('symbols', []),
            'interval': strategy_config.get('interval'),
            'strategy_params': strategy_config.get('strategy_params', {}),
            'orchestrator_status': strategy_config.get('orchestrator_status', 'active'),
            'is_trading_enabled': strategy_config.get('is_trading_enabled', False),
            'rl_model_id': rl_model_id
        }
        
        strategy_ref.set(strategy_data, merge=True)
        print(f"--- [DATABASE] Strateji '{strategy_id}' başarıyla kaydedildi/güncellendi. ---")
        
    except Exception as e:
        print(f"--- [HATA] Strateji kaydedilemedi: {e} ---")
        raise

def remove_strategy(strategy_id):
    """
    Bir stratejiyi ve o stratejiye ait TÜM ilişkili verileri
    (pozisyonlar, alarmlar vb.) veritabanından tamamen siler.
    """
    try:
        db = get_db()
        
        # İlişkili pozisyonları sil
        positions_ref = db.collection('positions')
        positions_query = positions_ref.where('strategy_id', '==', strategy_id).stream()
        for pos_doc in positions_query:
            pos_doc.reference.delete()
        
        # İlişkili alarmları sil
        alarms_ref = db.collection('alarms')
        alarms_query = alarms_ref.where('strategy_id', '==', strategy_id).stream()
        for alarm_doc in alarms_query:
            alarm_doc.reference.delete()
        
        # İlişkili manuel işlemleri sil
        actions_ref = db.collection('manual_actions')
        actions_query = actions_ref.where('strategy_id', '==', strategy_id).stream()
        for action_doc in actions_query:
            action_doc.reference.delete()
        
        # Ana strateji kaydını sil
        strategy_ref = db.collection('strategies').document(strategy_id)
        strategy_ref.delete()
        
        print(f"--- [DATABASE] Strateji (ID: {strategy_id}) ve tüm ilişkili verileri başarıyla silindi. ---")
    except Exception as e:
        print(f"--- [HATA] Strateji silinemedi: {e} ---")
        raise

@st.cache_data(ttl=15)
def get_all_strategies():
    """Tüm stratejileri döndürür."""
    try:
        db = get_db()
        strategies_ref = db.collection('strategies').stream()
        result = []
        for doc in strategies_ref:
            data = doc.to_dict()
            data['id'] = doc.id
            result.append(data)
        return result
    except Exception as e:
        print(f"--- [HATA] Stratejiler alınamadı: {e} ---")
        return []

def update_position(strategy_id, symbol, position, entry_price, sl_price=0, tp1_price=0, tp2_price=0, tp1_hit=False, tp2_hit=False):
    """Bir pozisyonu ekler veya günceller."""
    try:
        db = get_db()
        position_id = f"{strategy_id}_{symbol}"
        position_ref = db.collection('positions').document(position_id)
        
        position_data = {
            'strategy_id': strategy_id,
            'symbol': symbol,
            'position': position,
            'entry_price': entry_price,
            'stop_loss_price': sl_price,
            'tp1_price': tp1_price,
            'tp2_price': tp2_price,
            'tp1_hit': tp1_hit,
            'tp2_hit': tp2_hit
        }
        
        position_ref.set(position_data, merge=True)
    except Exception as e:
        print(f"--- [HATA] Pozisyon güncellenemedi: {e} ---")
        raise

def get_positions_for_strategy(strategy_id):
    """Bir strateji için tüm pozisyonları döndürür."""
    try:
        db = get_db()
        positions_ref = db.collection('positions')
        positions_query = positions_ref.where('strategy_id', '==', strategy_id).stream()
        
        positions = {}
        for doc in positions_query:
            data = doc.to_dict()
            positions[data['symbol']] = data
        return positions
    except Exception as e:
        print(f"--- [HATA] Pozisyonlar alınamadı: {e} ---")
        return {}

def log_alarm_db(strategy_id, symbol, signal, price):
    """Bir alarm/sinyal kaydı oluşturur."""
    try:
        db = get_db()
        alarm_ref = db.collection('alarms').document()
        alarm_ref.set({
            'strategy_id': strategy_id,
            'timestamp': firestore.SERVER_TIMESTAMP,
            'symbol': symbol,
            'signal': signal,
            'price': price
        })
    except Exception as e:
        print(f"--- [HATA] Alarm kaydedilemedi: {e} ---")

@st.cache_data(ttl=60)
def get_alarm_history_db(limit=50):
    """Alarm geçmişini döndürür."""
    try:
        db = get_db()
        alarms_ref = db.collection('alarms').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(limit).stream()
        
        alarms = []
        for doc in alarms_ref:
            data = doc.to_dict()
            alarms.append({
                'Zaman': data.get('timestamp'),
                'Sembol': data.get('symbol'),
                'Sinyal': data.get('signal'),
                'Fiyat': data.get('price')
            })
        
        return pd.DataFrame(alarms) if alarms else pd.DataFrame(columns=['Zaman', 'Sembol', 'Sinyal', 'Fiyat'])
    except Exception as e:
        print(f"--- [HATA] Alarm geçmişi alınamadı: {e} ---")
        return pd.DataFrame(columns=['Zaman', 'Sembol', 'Sinyal', 'Fiyat'])

@st.cache_data(ttl=15)
def get_all_open_positions():
    """Tüm açık pozisyonları döndürür."""
    try:
        db = get_db()
        positions_ref = db.collection('positions')
        positions_query = positions_ref.where('position', '!=', '').where('position', '!=', None).stream()
        
        positions = []
        for doc in positions_query:
            pos_data = doc.to_dict()
            if pos_data.get('position'):
                # Strateji bilgisini al
                strategy_ref = db.collection('strategies').document(pos_data['strategy_id'])
                strategy_doc = strategy_ref.get()
                strategy_name = strategy_doc.to_dict().get('name', '') if strategy_doc.exists else ''
                
                positions.append({
                    'strategy_id': pos_data['strategy_id'],
                    'Strateji Adı': strategy_name,
                    'Sembol': pos_data['symbol'],
                    'Pozisyon': pos_data['position'],
                    'Giriş Fiyatı': pos_data.get('entry_price', 0),
                    'Stop Loss': pos_data.get('stop_loss_price', 0),
                    'TP1': pos_data.get('tp1_price', 0),
                    'TP2': pos_data.get('tp2_price', 0)
                })
        
        return pd.DataFrame(positions) if positions else pd.DataFrame()
    except Exception as e:
        print(f"--- [HATA] Açık pozisyonlar alınamadı: {e} ---")
        return pd.DataFrame()

def update_strategy_status(strategy_id, status, is_orchestrator_decision=False):
    """Bir stratejinin durumunu günceller."""
    try:
        db = get_db()
        strategy_ref = db.collection('strategies').document(strategy_id)
        
        if is_orchestrator_decision:
            strategy_ref.update({'orchestrator_status': status})
        else:
            strategy_ref.update({'status': status})
    except Exception as e:
        print(f"--- [HATA] Strateji durumu güncellenemedi: {e} ---")
        raise

def issue_manual_action(strategy_id, symbol, action):
    """Manuel bir işlem kaydı oluşturur."""
    try:
        db = get_db()
        action_ref = db.collection('manual_actions').document()
        action_ref.set({
            'strategy_id': strategy_id,
            'symbol': symbol,
            'action': action,
            'timestamp': firestore.SERVER_TIMESTAMP,
            'status': 'pending'
        })
    except Exception as e:
        print(f"--- [HATA] Manuel işlem kaydedilemedi: {e} ---")
        raise

def get_and_clear_pending_actions(strategy_id):
    """Bekleyen manuel işlemleri alır ve tamamlandı olarak işaretler."""
    try:
        db = get_db()
        actions_ref = db.collection('manual_actions')
        actions_query = actions_ref.where('strategy_id', '==', strategy_id).where('status', '==', 'pending').stream()
        
        actions = []
        for doc in actions_query:
            data = doc.to_dict()
            actions.append({
                'id': doc.id,
                'symbol': data.get('symbol'),
                'action': data.get('action')
            })
            # Durumu güncelle
            doc.reference.update({'status': 'completed'})
        
        return actions
    except Exception as e:
        print(f"--- [HATA] Bekleyen işlemler alınamadı: {e} ---")
        return []

@st.cache_data(ttl=30)
def get_live_closed_trades_metrics(strategy_id=None):
    """Canlı kapanan işlemlerin metriklerini hesaplar."""
    from database import get_all_strategies
    
    default_metrics = {
        "Toplam İşlem": 0, "Başarı Oranı (%)": 0.0, "Toplam Getiri (%)": 0.0,
        "Ortalama Kazanç (%)": 0.0, "Ortalama Kayıp (%)": 0.0, "Profit Factor": 0.0
    }
    
    try:
        all_strategies = {s['id']: s for s in get_all_strategies()}
        db = get_db()
        
        # Alarmları al
        alarms_ref = db.collection('alarms')
        if strategy_id:
            alarms_query = alarms_ref.where('strategy_id', '==', strategy_id).order_by('timestamp', direction=firestore.Query.ASCENDING).stream()
        else:
            alarms_query = alarms_ref.order_by('timestamp', direction=firestore.Query.ASCENDING).stream()
        
        alarms = []
        for doc in alarms_query:
            data = doc.to_dict()
            signal = data.get('signal', '')
            if any(keyword in signal for keyword in ['Yeni', 'Kapatıldı', 'Stop-Loss', 'Karşıt Sinyal']):
                alarms.append({
                    'strategy_id': data.get('strategy_id'),
                    'symbol': data.get('symbol'),
                    'signal': signal,
                    'price': data.get('price'),
                    'timestamp': data.get('timestamp')
                })
        
        if not alarms:
            return default_metrics
        
        # İşlemleri hesapla
        trades = []
        open_trades = {}
        
        for alarm in alarms:
            key = (alarm['strategy_id'], alarm['symbol'])
            signal = alarm['signal']
            price = alarm['price']
            strategy_id_current = alarm['strategy_id']
            
            if 'Yeni' in signal and key not in open_trades:
                strategy_config = all_strategies.get(strategy_id_current, {})
                strategy_params = strategy_config.get('strategy_params', {})
                open_trades[key] = {
                    'entry_price': price,
                    'position_type': 'Long' if 'LONG' in signal.upper() else 'Short',
                    'position_size': 100.0,
                    'tp1_size_pct': strategy_params.get('tp1_size_pct', 50.0),
                    'tp2_size_pct': strategy_params.get('tp2_size_pct', 50.0)
                }
            elif ('Kapatıldı' in signal or 'Stop-Loss' in signal or 'Karşıt Sinyal' in signal) and key in open_trades:
                trade_info = open_trades[key]
                entry_price = trade_info['entry_price']
                position_type = trade_info['position_type']
                
                pnl = ((price - entry_price) / entry_price) * 100 if position_type == 'Long' else ((entry_price - price) / entry_price) * 100
                
                size_closed = 0
                if 'Take-Profit 1' in signal:
                    size_closed = trade_info['tp1_size_pct']
                elif 'Take-Profit 2' in signal:
                    size_closed = trade_info['position_size']
                else:
                    size_closed = trade_info['position_size']
                
                trades.append({'pnl': pnl, 'size': size_closed})
                trade_info['position_size'] -= size_closed
                
                if trade_info['position_size'] <= 0.1:
                    del open_trades[key]
        
        if not trades:
            return default_metrics
        
        total_pnl = sum(t['pnl'] * (t['size'] / 100.0) for t in trades)
        pnl_list = [t['pnl'] for t in trades]
        total_trades_count = len(pnl_list)
        winning_trades = [p for p in pnl_list if p > 0]
        losing_trades = [p for p in pnl_list if p <= 0]
        
        win_rate = (len(winning_trades) / total_trades_count) * 100 if total_trades_count > 0 else 0
        avg_win = sum(winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = abs(sum(losing_trades) / len(losing_trades)) if losing_trades else 0
        
        gross_profit = sum(winning_trades)
        gross_loss = abs(sum(losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf
        
        return {
            "Toplam İşlem": total_trades_count,
            "Başarı Oranı (%)": round(win_rate, 2),
            "Toplam Getiri (%)": round(total_pnl, 2),
            "Ortalama Kazanç (%)": round(avg_win, 2),
            "Ortalama Kayıp (%)": round(avg_loss, 2),
            "Profit Factor": round(profit_factor, 2)
        }
    except Exception as e:
        print(f"--- [HATA] Metrikler hesaplanamadı: {e} ---")
        return default_metrics

def remove_rl_model_by_id(model_id):
    """Veritabanından bir RL modelini ID'sine göre siler."""
    try:
        db = get_db()
        
        # Firestore'dan model bilgisini al
        model_ref = db.collection('rl_models').document(str(model_id))
        model_doc = model_ref.get()
        
        if model_doc.exists:
            model_data = model_doc.to_dict()
            storage_path = model_data.get('storage_path')
            storage_type = model_data.get('storage_type', 'firebase_storage')
            
            # Storage tipine göre dosyayı sil
            if storage_type == 'firebase_storage':
                bucket = get_storage_bucket()
                if storage_path and bucket:
                    try:
                        blob = bucket.blob(storage_path)
                        blob.delete()
                        print(f"--- [DATABASE] Firebase Storage'dan model dosyası silindi: {storage_path}")
                    except Exception as e:
                        print(f"--- [UYARI] Firebase Storage'dan silinemedi: {e}")
            elif storage_type == 'local_file':
                # Yerel dosyayı sil
                if storage_path and os.path.exists(storage_path):
                    try:
                        os.remove(storage_path)
                        print(f"--- [DATABASE] Yerel model dosyası silindi: {storage_path}")
                    except Exception as e:
                        print(f"--- [UYARI] Yerel dosya silinemedi: {e}")
            
            # Firestore'dan kaydı sil
            model_ref.delete()
            print(f"--- [DATABASE] RL Modeli (ID: {model_id}) başarıyla silindi. ---")
        else:
            print(f"--- [UYARI] RL Modeli (ID: {model_id}) bulunamadı. ---")
    except Exception as e:
        print(f"--- [HATA] RL Modeli silinemedi: {e} ---")
        raise
