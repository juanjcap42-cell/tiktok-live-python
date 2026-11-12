from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, LikeEvent, GiftEvent
from filtros import FiltrosManager
import threading
import asyncio
import os
import functools

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'top-tap-tap-secret-key-2026')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

client = None
filtros_manager = FiltrosManager()

# Estado de configuración de voz
config_voz = {
    'vozActivada': False,
    'soloSeguidores': False,
    'soloDonadores': False,
    'nivelDonadorMinimo': 1,
    'soloQuiéreme': False,
    'cantidadQuiéremeMinima': 1
}

# Seguimiento de usuarios
seguidores = set()
donadores = {}

# Ranking de likes (tap tap)
ranking_likes = {}

# Posiciones anteriores para detectar cambios
posiciones_anteriores = {}

# Base de datos de usuarios (temporal - se reemplazará con Firebase)
usuarios_db = {}

# ============ DECORADOR PARA PROTEGER RUTAS ============
def login_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ============ RUTAS PÚBLICAS ============
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
        
        # Validaciones
        if not nombre or not email or not password:
            flash('Todos los campos son obligatorios', 'error')
            return render_template('register.html')
        
        if password != confirm_password:
            flash('Las contraseñas no coinciden', 'error')
            return render_template('register.html')
        
        if len(password) < 6:
            flash('La contraseña debe tener al menos 6 caracteres', 'error')
            return render_template('register.html')
        
        if email in usuarios_db:
            flash('Este correo ya está registrado', 'error')
            return render_template('register.html')
        
        # Crear usuario (temporal - se reemplazará con Firebase)
        usuarios_db[email] = {
            'nombre': nombre,
            'email': email,
            'password': password,  # En producción se debe hashear
            'fecha_registro': '2026-11-12'
        }
        
        print(f'✅ Usuario registrado: {nombre} ({email})')
        flash('Cuenta creada exitosamente. Ahora puedes iniciar sesión.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        if not email or not password:
            flash('Correo y contraseña son obligatorios', 'error')
            return render_template('login.html')
        
        # Verificar usuario (temporal - se reemplazará con Firebase)
        if email in usuarios_db and usuarios_db[email]['password'] == password:
            session['user_id'] = email
            session['user_name'] = usuarios_db[email]['nombre']
            print(f'✅ Usuario inició sesión: {email}')
            return redirect(url_for('dashboard'))
        else:
            flash('Correo o contraseña incorrectos', 'error')
            return render_template('login.html')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ============ RUTAS PROTEGIDAS ============
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

# ============ EVENTOS SOCKET.IO ============
@socketio.on('conectar')
def handle_conectar(data):
    global client
    username = data['username'].replace('@', '')
    
    print(f'🔄 Conectando a @{username}...')
    
    client = TikTokLiveClient(unique_id=username)
    
    @client.on(ConnectEvent)
    async def on_connect(event):
        print(f'✅ Conectado! Room ID: {event.room_id}')
        socketio.emit('log', {'msg': f'✅ Conectado a @{username}', 'type': 'success'})
    
    @client.on(CommentEvent)
    async def on_comment(event):
        try:
            user = event.user
            unique_id = get_unique_id(user)
            nickname = get_nickname(user)
            comentario = event.comment
            
            print(f'💬 {nickname} ({unique_id}): {comentario}')
            
            permitido, razon = filtros_manager.filtrar_mensaje(unique_id, nickname, comentario)
            
            if not permitido:
                print(f'🚫 {razon}: {nickname} - {comentario}')
                socketio.emit('log', {'msg': f'🚫 {razon}', 'type': 'error'})
                return
            
            texto_limpio = filtros_manager.limpiar_texto_para_tts(comentario)
            
            socketio.emit('chat', {
                'nickname': nickname,
                'comment': comentario,
                'avatar': get_avatar_url(user),
                'uniqueId': unique_id
            })
            
            if config_voz['vozActivada']:
                debe_hablar = True
                
                if config_voz['soloSeguidores']:
                    debe_hablar = unique_id in seguidores
                
                if config_voz['soloDonadores'] and debe_hablar:
                    info_donador = donadores.get(unique_id, {'totalDiamantes': 0})
                    nivel_min = config_voz['nivelDonadorMinimo']
                    
                    if nivel_min == 1 and info_donador['totalDiamantes'] < 1:
                        debe_hablar = False
                    elif nivel_min == 2 and info_donador['totalDiamantes'] < 50:
                        debe_hablar = False
                    elif nivel_min == 3 and info_donador['totalDiamantes'] < 100:
                        debe_hablar = False
                    elif nivel_min == 4 and info_donador['totalDiamantes'] < 500:
                        debe_hablar = False
                    elif nivel_min == 5 and info_donador['totalDiamantes'] < 1000:
                        debe_hablar = False
                
                if debe_hablar:
                    nombre_limpio = filtros_manager.limpiar_nombre_para_tts(nickname)
                    texto_tts = f"{nombre_limpio} dice: {texto_limpio}"
                    socketio.emit('tts', {'texto': texto_tts})
                    print(f'🔊 Enviado TTS: {texto_tts[:50]}...')
                    
        except Exception as e:
            print(f'❌ Error en on_comment: {e}')
    
    @client.on(LikeEvent)
    async def on_like(event):
        try:
            user = event.user
            unique_id = get_unique_id(user)
            nickname = get_nickname(user)
            likes = getattr(event, 'like_count', getattr(event, 'total_count', 1))
            
            seguidores.add(unique_id)
            
            if unique_id not in ranking_likes:
                ranking_likes[unique_id] = {
                    'uniqueId': unique_id,
                    'nickname': nickname,
                    'avatar': get_avatar_url(user),
                    'totalLikes': 0
                }
            
            ranking_likes[unique_id]['totalLikes'] += likes
            ranking_likes[unique_id]['nickname'] = nickname
            
            avatar_url = get_avatar_url(user)
            if avatar_url and (not ranking_likes[unique_id]['avatar'] or ranking_likes[unique_id]['avatar'] == ''):
                ranking_likes[unique_id]['avatar'] = avatar_url
            
            print(f'❤️ {nickname} dio {likes} likes')
            
            socketio.emit('like', {
                'nickname': nickname,
                'likes': likes,
                'avatar': get_avatar_url(user),
                'uniqueId': unique_id
            })
            
            enviar_ranking_actualizado()
            
        except Exception as e:
            print(f'❌ Error en on_like: {e}')
    
    @client.on(GiftEvent)
    async def on_gift(event):
        try:
            user = event.user
            unique_id = get_unique_id(user)
            nickname = get_nickname(user)
            nombre_regalo = event.gift.name
            diamantes = event.gift.diamond_count
            
            if unique_id not in donadores:
                donadores[unique_id] = {'totalDiamantes': 0, 'rosas': 0}
            
            donadores[unique_id]['totalDiamantes'] += diamantes
            
            if 'rose' in nombre_regalo.lower() or 'quiéreme' in nombre_regalo.lower():
                donadores[unique_id]['rosas'] += 1
                rosas_actuales = donadores[unique_id]['rosas']
                
                print(f'🌹 {nickname} envió rosa #{rosas_actuales}')
                
                if config_voz['soloQuiéreme']:
                    min_rosas = config_voz['cantidadQuiéremeMinima']
                    if rosas_actuales >= min_rosas:
                        nombre_limpio = filtros_manager.limpiar_nombre_para_tts(nickname)
                        texto_tts = f"{nombre_limpio} envió una rosa Quiéreme"
                        socketio.emit('tts', {'texto': texto_tts})
                        print(f'🔊 Enviado TTS: {texto_tts}')
            
            print(f'🎁 {nickname} envió {nombre_regalo} ({diamantes} 💎)')
            socketio.emit('gift', {
                'nickname': nickname,
                'gift': nombre_regalo,
                'diamonds': diamantes,
                'avatar': get_avatar_url(user),
                'uniqueId': unique_id
            })
            
        except Exception as e:
            print(f'❌ Error en on_gift: {e}')
    
    threading.Thread(target=lambda: asyncio.run(client.run()), daemon=True).start()
    socketio.emit('log', {'msg': f'⏳ Conectando a @{username}...', 'type': 'info'})

@socketio.on('desconectar')
def handle_desconectar():
    global client
    if client:
        client.stop()
        client = None
    socketio.emit('log', {'msg': '📴 Desconectado', 'type': 'info'})

@socketio.on('config-voz')
def handle_config_voz(config):
    global config_voz
    
    if 'vozActivada' in config:
        config_voz['vozActivada'] = config['vozActivada']
        if config['vozActivada']:
            socketio.emit('log', {'msg': '🔊 Chat de voz ACTIVADO', 'type': 'success'})
        else:
            socketio.emit('log', {'msg': '🔇 Chat de voz DESACTIVADO', 'type': 'info'})
    
    if 'soloSeguidores' in config:
        config_voz['soloSeguidores'] = config['soloSeguidores']
    
    if 'soloDonadores' in config:
        config_voz['soloDonadores'] = config['soloDonadores']
    
    if 'nivelDonadorMinimo' in config:
        config_voz['nivelDonadorMinimo'] = config['nivelDonadorMinimo']
    
    if 'soloQuiéreme' in config:
        config_voz['soloQuiéreme'] = config['soloQuiéreme']
    
    if 'cantidadQuiéremeMinima' in config:
        config_voz['cantidadQuiéremeMinima'] = config['cantidadQuiéremeMinima']
    
    if 'filtros' in config:
        filtros_manager.set_config(config['filtros'])
        socketio.emit('log', {'msg': '⚙️ Filtros actualizados', 'type': 'success'})
    
    print(f'⚙️ Config voz: {config_voz}')

@socketio.on('actualizar-filtros')
def handle_actualizar_filtros(config):
    filtros_manager.set_config(config)
    socketio.emit('log', {'msg': '✅ Filtros actualizados', 'type': 'success'})

@socketio.on('solicitar-ranking')
def handle_solicitar_ranking():
    enviar_ranking_actualizado()

def enviar_ranking_actualizado():
    global posiciones_anteriores
    
    ranking_ordenado = sorted(
        ranking_likes.values(),
        key=lambda x: x['totalLikes'],
        reverse=True
    )[:6]
    
    cambios = []
    for i, usuario in enumerate(ranking_ordenado):
        unique_id = usuario['uniqueId']
        posicion_actual = i + 1
        
        if unique_id in posiciones_anteriores:
            posicion_anterior = posiciones_anteriores[unique_id]
            
            if posicion_anterior > posicion_actual:
                cambios.append({
                    'uniqueId': unique_id,
                    'nickname': usuario['nickname'],
                    'avatar': usuario['avatar'],
                    'posicionAnterior': posicion_anterior,
                    'posicionActual': posicion_actual,
                    'tipo': 'subio'
                })
                print(f'🚀 {usuario["nickname"]} SUBIÓ de #{posicion_anterior} a #{posicion_actual}')
            elif posicion_anterior < posicion_actual:
                cambios.append({
                    'uniqueId': unique_id,
                    'nickname': usuario['nickname'],
                    'avatar': usuario['avatar'],
                    'posicionAnterior': posicion_anterior,
                    'posicionActual': posicion_actual,
                    'tipo': 'bajo'
                })
                print(f'⬇️ {usuario["nickname"]} BAJÓ de #{posicion_anterior} a #{posicion_actual}')
        
        posiciones_anteriores[unique_id] = posicion_actual
    
    if cambios:
        socketio.emit('cambio-posicion', cambios)
    
    socketio.emit('ranking-actualizado', ranking_ordenado)

# ============ FUNCIONES AUXILIARES ============
def get_unique_id(user):
    return getattr(user, 'unique_id', None) or getattr(user, 'uniqueId', None) or str(getattr(user, 'id', 'unknown'))

def get_nickname(user):
    return getattr(user, 'nickname', None) or getattr(user, 'uniqueId', 'Usuario')

def get_avatar_url(user):
    try:
        if hasattr(user, 'avatar_thumb') and user.avatar_thumb:
            if hasattr(user.avatar_thumb, 'url_list'):
                return user.avatar_thumb.url_list[0] if user.avatar_thumb.url_list else None
        if hasattr(user, 'profile_pic') and user.profile_pic:
            if hasattr(user.profile_pic, 'url_list'):
                return user.profile_pic.url_list[0] if user.profile_pic.url_list else None
        if isinstance(getattr(user, 'avatar_thumb', None), str):
            return user.avatar_thumb
        return None
    except:
        return None

# ============ INICIO DEL SERVIDOR ============
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    print('🚀 Servidor Top Tap Tap iniciado')
    print(f'📡 Puerto: {port}')
    print('🏆 Landing: http://localhost:' + str(port) + '/')
    print('📝 Registro: http://localhost:' + str(port) + '/register')
    print('🔐 Login: http://localhost:' + str(port) + '/login')
    print('📊 Dashboard: http://localhost:' + str(port) + '/dashboard')
    print('🎙️ Chat de voz listo')
    
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)