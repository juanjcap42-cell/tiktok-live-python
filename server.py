from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, LikeEvent, GiftEvent
from filtros import FiltrosManager
import threading
import asyncio
import os
import functools
import json
from datetime import datetime

# Firebase Admin SDK
import firebase_admin
from firebase_admin import credentials, firestore

# ============ 1. INICIALIZAR FIREBASE ============
if not firebase_admin._apps:
    try:
        cred_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', 'firebase-credentials.json')
        
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            print(f"✅ Firebase conectado desde archivo: {cred_path}")
        else:
            cred_json = os.environ.get('FIREBASE_CREDENTIALS')
            if cred_json:
                cred_dict = json.loads(cred_json)
                cred = credentials.Certificate(cred_dict)
                firebase_admin.initialize_app(cred)
                print("✅ Firebase conectado desde variable de entorno")
            else:
                print("⚠️ Firebase NO configurado. Modo local sin base de datos.")
    except Exception as e:
        print(f"❌ Error al inicializar Firebase: {e}")

db = firestore.client() if firebase_admin._apps else None
if db:
    print("📊 Firestore listo para operaciones")

# ============ 2. CONFIGURACIÓN DE FLASK Y SOCKET.IO ============
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'top-tap-tap-secret-key-2026')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

client = None
filtros_manager = FiltrosManager()

config_voz = {
    'vozActivada': False,
    'soloSeguidores': False,
    'soloDonadores': False,
    'nivelDonadorMinimo': 1,
    'soloQuiéreme': False,
    'cantidadQuiéremeMinima': 1
}

seguidores = set()
donadores = {}
ranking_likes = {}
posiciones_anteriores = {}

# ============ 3. FUNCIONES DE FIREBASE ============
def guardar_seguidor(streamer_email, unique_id, nickname, avatar):
    if db is None: return
    try:
        streamer_ref = db.collection('streamers').document(streamer_email)
        seguidor_ref = streamer_ref.collection('seguidores').document(unique_id)
        seguidor_ref.set({
            'uniqueId': unique_id,
            'nickname': nickname,
            'avatar': avatar or '',
            'primera_vez': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'ultima_vez': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }, merge=True)
    except Exception as e:
        print(f'❌ Error guardando seguidor: {e}')

def guardar_donador(streamer_email, unique_id, nickname, diamantes, rosas=0):
    if db is None: return
    try:
        streamer_ref = db.collection('streamers').document(streamer_email)
        donador_ref = streamer_ref.collection('donadores').document(unique_id)
        
        donador_actual = donador_ref.get()
        if donador_actual.exists:
            datos = donador_actual.to_dict()
            total_diamantes = datos.get('totalDiamantes', 0) + diamantes
            total_rosas = datos.get('rosas', 0) + rosas
            primera_vez = datos.get('primera_vez', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        else:
            total_diamantes = diamantes
            total_rosas = rosas
            primera_vez = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        donador_ref.set({
            'uniqueId': unique_id,
            'nickname': nickname,
            'totalDiamantes': total_diamantes,
            'rosas': total_rosas,
            'primera_vez': primera_vez,
            'ultima_vez': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        print(f'❌ Error guardando donador: {e}')

def cargar_seguidores(streamer_email):
    if db is None: return set()
    try:
        streamer_ref = db.collection('streamers').document(streamer_email)
        seguidores_ref = streamer_ref.collection('seguidores').stream()
        return {doc.id for doc in seguidores_ref}
    except Exception as e:
        print(f'❌ Error cargando seguidores: {e}')
        return set()

def cargar_donadores(streamer_email):
    if db is None: return {}
    try:
        streamer_ref = db.collection('streamers').document(streamer_email)
        donadores_ref = streamer_ref.collection('donadores').stream()
        return {
            doc.id: {'totalDiamantes': doc.to_dict().get('totalDiamantes', 0), 'rosas': doc.to_dict().get('rosas', 0)}
            for doc in donadores_ref
        }
    except Exception as e:
        print(f'❌ Error cargando donadores: {e}')
        return {}

# ============ 4. DECORADOR DE PROTECCIÓN ============
def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ============ 5. RUTAS PÚBLICAS ============
@app.route('/')
def home():
    return render_template('landing.html')

@app.route('/landing')
def landing():
    return render_template('landing.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirmPassword', '')
        
        if not nombre or not email or not password:
            flash('Todos los campos son obligatorios', 'error')
            return render_template('register.html')
        if password != confirm_password:
            flash('Las contraseñas no coinciden', 'error')
            return render_template('register.html')
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres', 'error')
            return render_template('register.html')
        if db is None:
            flash('Base de datos no configurada.', 'error')
            return render_template('register.html')
        
        try:
            streamer_ref = db.collection('streamers').document(email)
            if streamer_ref.get().exists:
                flash('Este correo ya está registrado', 'error')
                return render_template('register.html')
            
            streamer_ref.set({
                'nombre': nombre,
                'email': email,
                'password': password,
                'fecha_registro': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'tiktok_username': ''
            })
            print(f'✅ Usuario registrado: {nombre} ({email})')
            flash('Cuenta creada exitosamente.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            print(f'❌ Error registrando: {e}')
            flash('Error al registrar.', 'error')
            return render_template('register.html')
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Correo y contraseña son obligatorios', 'error')
            return render_template('login.html')
        if db is None:
            flash('Base de datos no configurada.', 'error')
            return render_template('login.html')
        
        try:
            streamer_ref = db.collection('streamers').document(email)
            doc = streamer_ref.get()
            
            if doc.exists and doc.to_dict().get('password') == password:
                session['user_id'] = email
                session['user_name'] = doc.to_dict().get('nombre', email)
                print(f'✅ Login: {email}')
                return redirect(url_for('dashboard'))
            else:
                flash('Correo o contraseña incorrectos', 'error')
                return render_template('login.html')
        except Exception as e:
            print(f'❌ Error login: {e}')
            flash('Error al iniciar sesión.', 'error')
            return render_template('login.html')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ============ 6. RUTAS PROTEGIDAS ============
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('index.html')

@app.route('/overlay')
def overlay():
    return render_template('overlay.html')

@app.route('/ranking')
def ranking():
    return render_template('ranking.html')

# ============ 7. EVENTOS SOCKET.IO ============
@socketio.on('conectar')
def handle_conectar(data):
    global client, seguidores, donadores
    
    if 'user_id' not in session:
        emit('log', {'msg': '❌ Debes iniciar sesión primero', 'type': 'error'})
        return
    
    streamer_email = session['user_id']
    username = data['username'].replace('@', '')
    
    print(f'🔍 [DEBUG] Conectando a @{username} desde {streamer_email}')
    
    if db:
        db.collection('streamers').document(streamer_email).update({'tiktok_username': username})
    
    seguidores = cargar_seguidores(streamer_email)
    donadores = cargar_donadores(streamer_email)
    print(f'📥 Datos cargados: {len(seguidores)} seguidores, {len(donadores)} donadores')
    
    print(f'🔄 Conectando a @{username}...')
    client = TikTokLiveClient(unique_id=username)
    
    @client.on(ConnectEvent)
    async def on_connect(event):
        print(f'✅ [DEBUG] Conectado! Room ID: {event.room_id}')
        socketio.emit('log', {'msg': f'✅ Conectado a @{username}', 'type': 'success'})
    
    @client.on(CommentEvent)
    async def on_comment(event):
        try:
            print('🔍 [DEBUG] === EVENTO COMMENT RECIBIDO ===')
            
            user = event.user
            unique_id = get_unique_id(user)
            nickname = get_nickname(user)
            comentario = event.comment
            
            print(f'🔍 [DEBUG] Usuario: {nickname} | ID: {unique_id} | Mensaje: {comentario}')
            
            # Mostrar SIEMPRE el comentario en el dashboard (para diagnóstico)
            socketio.emit('log', {'msg': f'💬 {nickname}: {comentario}', 'type': 'info'})
            
            # Verificar filtros
            print(f'🔍 [DEBUG] Configuración de filtros: {filtros_manager.get_config()}')
            permitido, razon = filtros_manager.filtrar_mensaje(unique_id, nickname, comentario)
            print(f'🔍 [DEBUG] ¿Permitido? {permitido} | Razón: {razon}')
            
            if not permitido:
                print(f'🚫 [DEBUG] FILTRADO: {razon}')
                socketio.emit('log', {'msg': f'🚫 {razon}: {nickname}', 'type': 'error'})
                return
            
            texto_limpio = filtros_manager.limpiar_texto_para_tts(comentario)
            print(f'🔍 [DEBUG] Texto limpio para TTS: {texto_limpio}')
            
            socketio.emit('chat', {
                'nickname': nickname,
                'comment': comentario,
                'avatar': get_avatar_url(user),
                'uniqueId': unique_id
            })
            
            if config_voz['vozActivada']:
                print(f'🔊 [DEBUG] Chat de voz ACTIVADO, procesando TTS...')
                debe_hablar = True
                
                if config_voz['soloSeguidores']:
                    es_seguidor = unique_id in seguidores
                    print(f'🔍 [DEBUG] ¿Es seguidor? {es_seguidor}')
                    debe_hablar = es_seguidor
                
                if config_voz['soloDonadores'] and debe_hablar:
                    info = donadores.get(unique_id, {'totalDiamantes': 0})
                    nivel = config_voz['nivelDonadorMinimo']
                    umbrales = {1: 1, 2: 50, 3: 100, 4: 500, 5: 1000}
                    umbral = umbrales.get(nivel, 1)
                    print(f'🔍 [DEBUG] Diamantes: {info["totalDiamantes"]} | Umbral: {umbral}')
                    if info['totalDiamantes'] < umbral:
                        debe_hablar = False
                
                if debe_hablar:
                    nombre_limpio = filtros_manager.limpiar_nombre_para_tts(nickname)
                    texto_tts = f"{nombre_limpio} dice: {texto_limpio}"
                    print(f'🔊 [DEBUG] EMITIENDO TTS: {texto_tts[:60]}')
                    socketio.emit('tts', {'texto': texto_tts})
                else:
                    print(f'🔇 [DEBUG] NO SE HABLA (debe_hablar=False)')
            else:
                print(f'🔇 [DEBUG] Chat de voz NO ACTIVADO (config_voz={config_voz["vozActivada"]})')
                
        except Exception as e:
            print(f'❌ [ERROR] on_comment: {e}')
            import traceback
            traceback.print_exc()
            socketio.emit('log', {'msg': f'❌ Error: {str(e)}', 'type': 'error'})
    
    @client.on(LikeEvent)
    async def on_like(event):
        try:
            user = event.user
            unique_id = get_unique_id(user)
            nickname = get_nickname(user)
            likes = getattr(event, 'like_count', getattr(event, 'total_count', 1))
            avatar = get_avatar_url(user)
            
            print(f'❤️ [DEBUG] LIKE: {nickname} dio {likes}')
            
            seguidores.add(unique_id)
            guardar_seguidor(streamer_email, unique_id, nickname, avatar)
            
            if unique_id not in ranking_likes:
                ranking_likes[unique_id] = {'uniqueId': unique_id, 'nickname': nickname, 'avatar': avatar, 'totalLikes': 0}
            
            ranking_likes[unique_id]['totalLikes'] += likes
            ranking_likes[unique_id]['nickname'] = nickname
            if avatar and not ranking_likes[unique_id]['avatar']:
                ranking_likes[unique_id]['avatar'] = avatar
            
            socketio.emit('like', {'nickname': nickname, 'likes': likes, 'avatar': avatar, 'uniqueId': unique_id})
            enviar_ranking_actualizado()
        except Exception as e:
            print(f'❌ [ERROR] on_like: {e}')
    
    @client.on(GiftEvent)
    async def on_gift(event):
        try:
            user = event.user
            unique_id = get_unique_id(user)
            nickname = get_nickname(user)
            nombre_regalo = event.gift.name
            diamantes = event.gift.diamond_count
            avatar = get_avatar_url(user)
            
            print(f'🎁 [DEBUG] GIFT: {nickname} envió {nombre_regalo} ({diamantes} 💎)')
            
            es_rosa = 'rose' in nombre_regalo.lower() or 'quiéreme' in nombre_regalo.lower()
            rosas = 1 if es_rosa else 0
            
            if unique_id not in donadores:
                donadores[unique_id] = {'totalDiamantes': 0, 'rosas': 0}
            
            donadores[unique_id]['totalDiamantes'] += diamantes
            if es_rosa: donadores[unique_id]['rosas'] += 1
            
            guardar_donador(streamer_email, unique_id, nickname, diamantes, rosas)
            
            if es_rosa and config_voz['soloQuiéreme']:
                if donadores[unique_id]['rosas'] >= config_voz['cantidadQuiéremeMinima']:
                    socketio.emit('tts', {'texto': f"{filtros_manager.limpiar_nombre_para_tts(nickname)} envió una rosa Quiéreme"})
            
            socketio.emit('gift', {'nickname': nickname, 'gift': nombre_regalo, 'diamonds': diamantes, 'avatar': avatar, 'uniqueId': unique_id})
        except Exception as e:
            print(f'❌ [ERROR] on_gift: {e}')
    
    # ✅ IMPORTANTE: Usar eventlet.spawn en lugar de threading.Thread
    print(f'🚀 [DEBUG] Iniciando bucle de TikTokLive...')
    eventlet.spawn(lambda: asyncio.run(client.run()))
    emit('log', {'msg': f'⏳ Conectando a @{username}...', 'type': 'info'})

@socketio.on('desconectar')
def handle_desconectar():
    global client
    if client:
        client.stop()
        client = None
    emit('log', {'msg': '📴 Desconectado', 'type': 'info'})

@socketio.on('config-voz')
def handle_config_voz(config):
    global config_voz
    print(f'🔧 [DEBUG] Actualizando config de voz: {config}')
    
    for key in ['vozActivada', 'soloSeguidores', 'soloDonadores', 'nivelDonadorMinimo', 'soloQuiéreme', 'cantidadQuiéremeMinima']:
        if key in config: config_voz[key] = config[key]
    if 'filtros' in config:
        filtros_manager.set_config(config['filtros'])
        emit('log', {'msg': '⚙️ Filtros actualizados', 'type': 'success'})
    
    print(f'🔧 [DEBUG] Config final: {config_voz}')
    
    estado = "ACTIVADO" if config_voz['vozActivada'] else "DESACTIVADO"
    emit('log', {'msg': f'🔊 Chat de voz {estado}', 'type': 'success' if config_voz['vozActivada'] else 'info'})

@socketio.on('actualizar-filtros')
def handle_actualizar_filtros(config):
    print(f'🔧 [DEBUG] Actualizando filtros: {config}')
    filtros_manager.set_config(config)
    emit('log', {'msg': '✅ Filtros actualizados', 'type': 'success'})

@socketio.on('solicitar-ranking')
def handle_solicitar_ranking():
    enviar_ranking_actualizado()

def enviar_ranking_actualizado():
    global posiciones_anteriores
    ranking_ordenado = sorted(ranking_likes.values(), key=lambda x: x['totalLikes'], reverse=True)[:6]
    
    cambios = []
    for i, usuario in enumerate(ranking_ordenado):
        unique_id = usuario['uniqueId']
        pos_actual = i + 1
        if unique_id in posiciones_anteriores:
            pos_anterior = posiciones_anteriores[unique_id]
            if pos_anterior > pos_actual:
                cambios.append({'uniqueId': unique_id, 'nickname': usuario['nickname'], 'avatar': usuario['avatar'], 'posicionAnterior': pos_anterior, 'posicionActual': pos_actual, 'tipo': 'subio'})
            elif pos_anterior < pos_actual:
                cambios.append({'uniqueId': unique_id, 'nickname': usuario['nickname'], 'avatar': usuario['avatar'], 'posicionAnterior': pos_anterior, 'posicionActual': pos_actual, 'tipo': 'bajo'})
        posiciones_anteriores[unique_id] = pos_actual
    
    if cambios: socketio.emit('cambio-posicion', cambios)
    socketio.emit('ranking-actualizado', ranking_ordenado)

# ============ 8. FUNCIONES AUXILIARES ============
def get_unique_id(user):
    return getattr(user, 'unique_id', None) or getattr(user, 'uniqueId', None) or str(getattr(user, 'id', 'unknown'))

def get_nickname(user):
    return getattr(user, 'nickname', None) or getattr(user, 'uniqueId', 'Usuario')

def get_avatar_url(user):
    try:
        if hasattr(user, 'avatar_thumb') and user.avatar_thumb and hasattr(user.avatar_thumb, 'url_list'):
            return user.avatar_thumb.url_list[0] if user.avatar_thumb.url_list else None
        if hasattr(user, 'profile_pic') and user.profile_pic and hasattr(user.profile_pic, 'url_list'):
            return user.profile_pic.url_list[0] if user.profile_pic.url_list else None
        return None
    except:
        return None

# ============ 9. INICIO DEL SERVIDOR ============
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    print('🚀 Servidor Top Tap Tap con Eventlet')
    print(f'📡 Puerto: {port}')
    
    import eventlet
    import eventlet.wsgi
    eventlet.wsgi.server(eventlet.listen(('0.0.0.0', port)), app)