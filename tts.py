import asyncio
import edge_tts
import os
import tempfile
import threading
import time
import subprocess

class TTSManager:
    def __init__(self):
        self.voz = "es-MX-JorgeNeural"  # Voz en español mexicano
        self.cola_mensajes = []
        self.temp_dir = tempfile.mkdtemp()
        self.esta_reproduciendo = False
        self.hilo_activo = False
    
    def set_voz(self, voz):
        self.voz = voz
    
    def reproducir_mp3_sin_vlc(self, archivo_mp3):
        """Reproduce el MP3 sin abrir VLC, usando MediaPlayer de PowerShell"""
        try:
            ruta_windows = archivo_mp3.replace('/', '\\')
            
            # Script de PowerShell que usa MediaPlayer (no abre ventanas)
            ps_script = f'''
            Add-Type -AssemblyName PresentationCore
            $player = New-Object System.Windows.Media.MediaPlayer
            $player.Open("{ruta_windows}")
            $player.Volume = 1.0
            $player.Play()
            Start-Sleep -Milliseconds 500
            while ($player.NaturalDuration.HasTimeSpan -eq $false) {{
                Start-Sleep -Milliseconds 100
            }}
            $duracion = $player.NaturalDuration.TimeSpan.TotalMilliseconds
            Start-Sleep -Milliseconds $duracion
            $player.Stop()
            $player.Close()
            '''
            
            subprocess.run(
                ['powershell', '-Command', ps_script],
                capture_output=True,
                timeout=60
            )
            return True
            
        except subprocess.TimeoutExpired:
            print('⚠️ Timeout de reproducción')
            return False
        except Exception as e:
            print(f'❌ Error reproduciendo: {e}')
            return False
    
    async def generar_audio(self, texto, archivo_salida):
        """Genera el audio con edge-tts"""
        communicate = edge_tts.Communicate(texto, self.voz)
        await communicate.save(archivo_salida)
    
    def procesar_cola(self):
        """Procesa la cola de mensajes"""
        print('🎧 Hilo de TTS iniciado (edge-tts en español)')
        self.hilo_activo = True
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        while self.hilo_activo:
            try:
                if len(self.cola_mensajes) > 0 and not self.esta_reproduciendo:
                    texto = self.cola_mensajes.pop(0)
                    
                    print(f'📢 Procesando: {texto[:50]}...')
                    
                    self.esta_reproduciendo = True
                    
                    # Generar archivo MP3
                    archivo_temp = os.path.join(self.temp_dir, f"tts_{int(time.time() * 1000)}.mp3")
                    
                    print(f'🔊 Generando audio con voz: {self.voz}')
                    loop.run_until_complete(self.generar_audio(texto, archivo_temp))
                    
                    if os.path.exists(archivo_temp):
                        tamano = os.path.getsize(archivo_temp)
                        print(f'✅ Audio generado ({tamano} bytes), reproduciendo...')
                        
                        # Reproducir sin abrir VLC
                        self.reproducir_mp3_sin_vlc(archivo_temp)
                        
                        print('✅ Reproducción completada')
                        
                        # Eliminar archivo
                        try:
                            os.remove(archivo_temp)
                        except:
                            pass
                    else:
                        print('❌ No se generó el audio')
                    
                    self.esta_reproduciendo = False
                    
                else:
                    time.sleep(0.1)
                    
            except Exception as e:
                print(f'❌ Error en cola TTS: {e}')
                self.esta_reproduciendo = False
                time.sleep(0.1)
    
    def agregar_a_cola(self, texto):
        self.cola_mensajes.append(texto)
        print(f'📥 Mensaje agregado a cola (total: {len(self.cola_mensajes)})')
    
    def iniciar_reproduccion(self):
        if not self.hilo_activo:
            threading.Thread(target=self.procesar_cola, daemon=True).start()
            print('🔊 Sistema de TTS iniciado correctamente (español)')
        else:
            print('⚠️ El TTS ya está activo')
    
    def detener_reproduccion(self):
        self.hilo_activo = False
        print('🔇 TTS detenido')
    
    def limpiar_temporales(self):
        try:
            for archivo in os.listdir(self.temp_dir):
                if archivo.endswith('.mp3'):
                    os.remove(os.path.join(self.temp_dir, archivo))
        except Exception as e:
            print(f'⚠️ Error limpiando: {e}')