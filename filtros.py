import re
from collections import defaultdict
from datetime import datetime, timedelta

class FiltrosManager:
    def __init__(self):
        self.config = {
            'filtroActivado': True,
            'bloquearGroserias': True,
            'bloquearEmojis': False,
            'bloquearNumeros': False,
            'bloquearEnlaces': True,
            'bloquearSpam': True,
            'banearAutomatico': False,  # ✅ Cambiado a False por defecto
            'tiempoBaneo': 300
        }
        
        self.groserias = [
            'puta', 'puto', 'mierda', 'pendejo', 'pendeja', 'idiota', 'estupido',
            'estupida', 'imbecil', 'cabron', 'cabrona', 'hijo de puta', 'verga',
            'culo', 'coño', 'carajo', 'joder', 'chingar', 'chingada', 'maricon',
            'maricona', 'bruto', 'bruta', 'tonto', 'tonta', 'pinche', 'naco', 'naca',
            'wey', 'guey', 'güey'  # ✅ 'we' eliminado
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
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE
        )
        return bool(emoji_pattern.search(texto))
    
    def contiene_numeros(self, texto):
        return bool(re.search(r'\d', texto))
    
    def contiene_enlaces(self, texto):
        url_pattern = re.compile(r'http[s]?://\S+')
        return bool(url_pattern.search(texto))
    
    def es_spam(self, unique_id, texto):
        """
        Detecta spam comparando SOLO el contenido del mensaje (sin menciones)
        """
        ahora = datetime.now()
        historial = self.historial_mensajes[unique_id]
        
        # Limpiar mensajes antiguos (más de 60 segundos)
        self.historial_mensajes[unique_id] = [
            (msg, tiempo) for msg, tiempo in historial 
            if (ahora - tiempo).total_seconds() < 60
        ]
        
        # Obtener mensajes recientes (últimos 10 segundos)
        mensajes_recientes = [
            msg for msg, tiempo in self.historial_mensajes[unique_id]
            if (ahora - tiempo).total_seconds() < 10
        ]
        
        # ✅ NORMALIZAR el texto: quitar menciones (@usuario) y emojis para comparar
        texto_normalizado = self.normalizar_para_comparar(texto)
        
        for msg in mensajes_recientes:
            msg_normalizado = self.normalizar_para_comparar(msg)
            if texto_normalizado == msg_normalizado:
                return True
        
        self.historial_mensajes[unique_id].append((texto, ahora))
        return False
    
    def normalizar_para_comparar(self, texto):
        """
        Normaliza el texto para comparación de spam:
        - Elimina menciones (@usuario)
        - Elimina emojis
        - Convierte a minúsculas
        - Elimina espacios extras
        """
        # Eliminar menciones (@usuario con o sin emojis)
        texto = re.sub(r'@[^\s]+', '', texto)
        
        # Eliminar emojis
        texto = re.sub(
            "["
            "\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "\U0001F900-\U0001F9FF"
            "\U0001FA00-\U0001FA6F"
            "\U0001F3FB-\U0001F3FF"
            "\u200D"
            "\uFE0F"
            "]+",
            "",
            texto,
            flags=re.UNICODE
        )
        
        # Convertir a minúsculas y limpiar espacios
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
        """
        Aplica filtros SOLO al contenido del mensaje, NO al nickname
        """
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
        
        # Filtrar emojis (SOLO si el mensaje es 100% emojis)
        if self.config['bloquearEmojis'] and self.contiene_emojis(mensaje_limpio):
            sin_emojis = re.sub(
                "["
                "\U0001F600-\U0001F64F"
                "\U0001F300-\U0001F5FF"
                "\U0001F680-\U0001F6FF"
                "\U0001F1E0-\U0001F1FF"
                "\U00002702-\U000027B0"
                "\U000024C2-\U0001F251"
                "]+",
                "",
                mensaje_limpio,
                flags=re.UNICODE
            ).strip()
            
            if not sin_emojis:
                return False, "Solo emojis"
        
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
        """Limpia el texto para TTS"""
        texto = re.sub(
            "["
            "\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            "",
            texto,
            flags=re.UNICODE
        )
        
        texto = re.sub(r'http[s]?://\S+', '', texto)
        texto = re.sub(r'[^\w\s.,!?¿¡-]', '', texto)
        texto = re.sub(r'\s+', ' ', texto).strip()
        
        return texto
    
    def limpiar_nombre_para_tts(self, nombre):
        """
        Limpia SOLO el nombre del usuario para TTS.
        Elimina emojis y caracteres especiales, dejando solo letras.
        """
        nombre_limpio = re.sub(
            "["
            "\U0001F600-\U0001F64F"
            "\U0001F300-\U0001F5FF"
            "\U0001F680-\U0001F6FF"
            "\U0001F1E0-\U0001F1FF"
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "\U0001F900-\U0001F9FF"
            "\U0001FA00-\U0001FA6F"
            "\U0001F3FB-\U0001F3FF"
            "\u200D"
            "\uFE0F"
            "]+",
            "",
            nombre,
            flags=re.UNICODE
        )
        
        nombre_limpio = re.sub(r'[^a-zA-ZáéíóúÁÉÍÓÚñÑüÜ\s]', '', nombre_limpio)
        nombre_limpio = re.sub(r'\s+', ' ', nombre_limpio).strip()
        
        if not nombre_limpio:
            nombre_limpio = "Usuario"
        
        return nombre_limpio