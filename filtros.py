import re
from collections import defaultdict
from datetime import datetime, timedelta

# ✅ Patrón de emojis COMPLETO compilado correctamente con re.compile()
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"   # Banderas / regional indicators
    "\U0001F300-\U0001F5FF"   # Símbolos y pictogramas
    "\U0001F600-\U0001F64F"   # Emoticones (caras)
    "\U0001F680-\U0001F6FF"   # Transporte y mapas
    "\U0001F700-\U0001F77F"   # Suplemento de símbolos
    "\U0001F780-\U0001F7FF"   # Geométricos extendidos
    "\U0001F800-\U0001F8FF"   # Suplemento de pictogramas
    "\U0001F900-\U0001F9FF"   # Emojis nuevos (🥰 🤔 🧠)
    "\U0001FA00-\U0001FAFF"   # Emojis muy nuevos (🫠 🫶)
    "\U00002600-\U000027BF"   # Misceláneos + Dingbats (❤ ☀ ✅)
    "\U00002B00-\U00002BFF"   # Símbolos varios
    "\U0000FE00-\U0000FE0F"   # Variation selectors (️)
    "\U0000200D"              # Zero-width joiner (👨‍👩‍👧)
    "\U0001F3FB-\U0001F3FF"   # Tono de piel (👋🏽)
    "\U00002190-\U000021FF"   # Flechas
    "\U00002300-\U000023FF"   # Misc técnica
    "]+",
    flags=re.UNICODE
)


class FiltrosManager:
    def __init__(self):
        self.config = {
            'filtroActivado': True,
            'bloquearGroserias': True,
            'bloquearEmojis': False,
            'bloquearNumeros': False,
            'bloquearEnlaces': True,
            'bloquearSpam': True,
            'banearAutomatico': False,
            'tiempoBaneo': 300
        }
        
        self.groserias = [
            'puta', 'puto', 'mierda', 'pendejo', 'pendeja', 'idiota', 'estupido',
            'estupida', 'imbecil', 'cabron', 'cabrona', 'hijo de puta', 'verga',
            'culo', 'coño', 'carajo', 'joder', 'chingar', 'chingada', 'maricon',
            'maricona', 'bruto', 'bruta', 'tonto', 'tonta', 'pinche', 'naco', 'naca',
            'wey', 'guey', 'güey'
        ]
        
        self.historial_mensajes = defaultdict(list)
        self.usuarios_baneados = {}
    
    def set_config(self, config):
        self.config.update(config)
    
    def get_config(self):
        return self.config
    
    def contiene_groserias(self, texto):
        texto_lower = texto.lower()
        for groseria in self.groserias:
            if groseria in texto_lower:
                return True
        return False
    
    def contiene_emojis(self, texto):
        """✅ Detecta CUALQUIER emoji usando patrón completo"""
        return bool(EMOJI_PATTERN.search(texto))
    
    def contiene_numeros(self, texto):
        return bool(re.search(r'\d', texto))
    
    def contiene_enlaces(self, texto):
        url_pattern = re.compile(r'http[s]?://\S+|www\.\S+')
        return bool(url_pattern.search(texto))
    
    def es_spam(self, unique_id, texto):
        ahora = datetime.now()
        historial = self.historial_mensajes[unique_id]
        
        self.historial_mensajes[unique_id] = [
            (msg, tiempo) for msg, tiempo in historial 
            if (ahora - tiempo).total_seconds() < 60
        ]
        
        mensajes_recientes = [
            msg for msg, tiempo in self.historial_mensajes[unique_id]
            if (ahora - tiempo).total_seconds() < 10
        ]
        
        texto_normalizado = self.normalizar_para_comparar(texto)
        
        for msg in mensajes_recientes:
            msg_normalizado = self.normalizar_para_comparar(msg)
            if texto_normalizado == msg_normalizado:
                return True
        
        self.historial_mensajes[unique_id].append((texto, ahora))
        return False
    
    def normalizar_para_comparar(self, texto):
        texto = re.sub(r'@[^\s]+', '', texto)
        texto = EMOJI_PATTERN.sub('', texto)
        texto = texto.lower().strip()
        texto = re.sub(r'\s+', ' ', texto)
        return texto
    
    def esta_baneado(self, unique_id):
        if unique_id in self.usuarios_baneados:
            tiempo_baneo = self.usuarios_baneados[unique_id]
            if datetime.now() < tiempo_baneo:
                return True
            else:
                del self.usuarios_baneados[unique_id]
        return False
    
    def banear_usuario(self, unique_id):
        tiempo_baneo = datetime.now() + timedelta(seconds=self.config['tiempoBaneo'])
        self.usuarios_baneados[unique_id] = tiempo_baneo
    
    def filtrar_mensaje(self, unique_id, nickname, texto):
        if self.esta_baneado(unique_id):
            return False, "Usuario baneado temporalmente"
        
        if not self.config['filtroActivado']:
            return True, ""
        
        mensaje_limpio = texto.strip()
        
        if not mensaje_limpio:
            return False, "Mensaje vacío"
        
        # Filtrar groserías
        if self.config['bloquearGroserias'] and self.contiene_groserias(mensaje_limpio):
            if self.config['banearAutomatico']:
                self.banear_usuario(unique_id)
                return False, f"Grosería detectada - {nickname} baneado"
            return False, "Contiene groserías"
        
        # ✅ FILTRO DE EMOJIS CORREGIDO:
        # Ahora bloquea CUALQUIER mensaje que contenga emojis
        if self.config['bloquearEmojis'] and self.contiene_emojis(mensaje_limpio):
            return False, "Contiene emojis"
        
        # Filtrar números
        if self.config['bloquearNumeros'] and self.contiene_numeros(mensaje_limpio):
            return False, "Contiene números"
        
        # Filtrar enlaces
        if self.config['bloquearEnlaces'] and self.contiene_enlaces(mensaje_limpio):
            if self.config['banearAutomatico']:
                self.banear_usuario(unique_id)
                return False, f"Enlace detectado - {nickname} baneado"
            return False, "Contiene enlaces"
        
        # Filtrar spam
        if self.config['bloquearSpam'] and self.es_spam(unique_id, mensaje_limpio):
            if self.config['banearAutomatico']:
                self.banear_usuario(unique_id)
                return False, f"Spam detectado - {nickname} baneado"
            return False, "Mensaje repetido"
        
        return True, ""
    
    def limpiar_texto_para_tts(self, texto):
        """
        ✅ Limpia el texto para que el TTS NUNCA lea emojis,
        aunque el filtro de emojis esté DESACTIVADO.
        """
        # 1. Quitar todos los emojis (patrón completo)
        texto = EMOJI_PATTERN.sub('', texto)
        
        # 2. Quitar enlaces
        texto = re.sub(r'http[s]?://\S+|www\.\S+', '', texto)
        
        # 3. Quitar menciones (@usuario)
        texto = re.sub(r'@[^\s]+', '', texto)
        
        # 4. Red de seguridad: eliminar cualquier carácter raro que quedó
        texto = re.sub(r'[^\w\s.,!?¿¡:;áéíóúÁÉÍÓÚñÑüÜ]', '', texto)
        
        # 5. Limpiar espacios extra
        texto = re.sub(r'\s+', ' ', texto).strip()
        
        return texto
    
    def limpiar_nombre_para_tts(self, nombre):
        """
        Limpia SOLO el nombre del usuario para TTS.
        """
        nombre_limpio = EMOJI_PATTERN.sub('', nombre)
        nombre_limpio = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]', '', nombre_limpio)
        nombre_limpio = re.sub(r'\s+', ' ', nombre_limpio).strip()
        
        if not nombre_limpio:
            nombre_limpio = "Usuario"
        
        return nombre_limpio