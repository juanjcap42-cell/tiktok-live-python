from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent, CommentEvent, LikeEvent, GiftEvent
from filtros import FiltrosManager
import threading
import asyncio
import os

app = Flask(__name__)
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

def get_unique_id(user):
    """Obtiene el unique_id del usuario de forma segura"""
    return getattr(user, 'unique_id', None) or getattr(user, 'uniqueId', None) or str(getattr(user, 'id', 'unknown'))

def get_nickname(user):
    """Obtiene el nickname del usuario de forma segura"""
    return getattr(user, 'nickname', None) or getattr(user, 'uniqueId', 'Usuario')

def get_avatar_url(user):
    """Extrae la URL del avatar de forma segura"""
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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/overlay')
def overlay():
    return render_template('overlay.html')

@app.route('/ranking')
def ranking():
    return render_template('ranking.html')

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
            
            # Aplicar filtros
            permitido, razon = filtros_manager.filtrar_mensaje(unique_id, nickname, comentario)
            
            if not permitido:
                print(f'🚫 {razon}: {nickname} - {comentario}')
                socketio.emit('log', {'msg': f'🚫 {razon}', 'type': 'error'})
                return
            
            texto_limpio = filtros_manager.limpiar_texto_para_tts(comentario)
            
            # Enviar al dashboard
            socketio.emit('chat', {
                'nickname': nickname,
                'comment': comentario,
                'avatar': get_avatar_url(user),
                'uniqueId': unique_id
            })
            
            # Si el chat de voz está activado, enviar al navegador
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
            import traceback
            traceback.print_exc()
    
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
            import traceback
            traceback.print_exc()
    
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
            import traceback
            traceback.print_exc()
    
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
            socketio.emit('log', {'msg': '🔊 Chat de voz ACTIVADO - Escucharás los mensajes', 'type': 'success'})
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
    print(f'⚙️ Config filtros: {filtros_manager.get_config()}')

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    
    print('🚀 Servidor iniciado')
    print(f'📡 Puerto: {port}')
    print('🎙️ Chat de voz listo - Actívalo desde el dashboard')
    
    from waitress import serve
    serve(app, host='0.0.0.0', port=port)