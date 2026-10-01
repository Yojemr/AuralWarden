# Arquitectura

AuralWarden mantiene el backend separado de la interfaz. Ningún componente del núcleo depende de PySide6.

```text
URL / archivo --------> Streamlink / FFmpeg --+
Subtítulos YouTube ---> yt-dlp / JSON3 o VTT --+----> detección auxiliar
Audio de Windows -----> WASAPI loopback -------+----> PCM mono 16 kHz
Micrófono ------------> WASAPI / respaldo -----+
                                                    |
                                                    v
                                      +-------------+----------+
                                      |                        |
                                  Búfer RAM           Ventanas solapadas
                                      |                        |
                                      |          selector de inferencia
                                      |       faster-whisper / whisper.cpp
                                      |                 + VAD
                                      |                segunda pasada
                                      |                        |
                                      |                  sherpa-onnx
                                      |                   hablantes
                                      |                        |
                                      +------> detección temporal
                                                               |
                  URL con vídeo -> segmentos temporales        |
                                      |                        |
                                      +----> trabajador MP4 <--+
                                                               |
                                      +------------------------+---------+
                                      |                        |         |
                                  WAV / MP4             registro JSONL EventBus
                                                                         |
                                                                     interfaz Qt
```

## Componentes

- `capture`: resolución Streamlink, respaldo directo FFmpeg, espera progresiva, reconexión y bloques PCM.
- `captions`: resolución pública de pistas YouTube, lectura incremental de JSON3 o WebVTT segmentado sobre M3U8 y entradas auxiliares.
- `windows_audio`: enumeración y captura local, remuestreo, medidor, silencio reversible y recuperación del volumen.
- `audio`: formato PCM, búfer circular y escritura WAV.
- `hardware`: inventario local y plan automático de motor, dispositivo, precisión, modelo e hilos.
- `transcribers`: contrato común, simulador y adaptadores `faster-whisper` y `whisper.cpp`.
- `components`: instalación versionada, verificada y aislada de motores opcionales.
- `diarization`: contrato, descarga de modelos y adaptador local sherpa-onnx.
- `engine`: ciclo de sesión, ventanas, segunda pasada y coordinación.
- `hotwords`: normalización, coincidencia exacta, difusa y candidatos.
- `detection`: fusión temporal de detecciones repetidas.
- `clips`: pre-roll, post-roll y clips de evidencia en audio.
- `video_clips`: selección de segmentos, remultiplexado asíncrono, clips MP4 y vídeo completo opcional.
- `session`: metadatos atómicos, eventos JSONL y diario incremental recuperable.
- `migration`: importación filtrada de preferencias y enlaces físicos a modelos sin trasladar evidencias.
- `events`: puente seguro entre hilos para consola e interfaz Qt.
- `resources`: métricas, historial breve y perfiles de carga.
- `transcript`: estado temporal y exportación solicitada.
- `source_info`: título público de la fuente con resolución asíncrona y alternativa local.
- `runtime_status`: estado local atómico que separa aplicación abierta y monitoreo activo.
- `local_control`: credencial, redacción y auditoría acotada del protocolo opcional para agentes; el transporte reutiliza la instancia única local de Qt.
- `filenames`: convenciones legibles y resolución de nombres repetidos.

## Aislamiento de dependencias

Streamlink, `faster-whisper`, CUDA y sherpa-onnx son extras independientes. Una distribución CPU no necesita cargar cuBLAS ni cuDNN. Los modelos se cargan de forma diferida únicamente al comenzar el procesamiento. Importar o diagnosticar AuralWarden no reserva VRAM.

El motor automático prioriza CUDA solo cuando detecta GPU, controlador y bibliotecas locales. En los demás equipos utiliza CPU `int8`. `whisper.cpp` es un adaptador externo: AuralWarden acepta componentes CPU y Vulkan, pero solo marca Vulkan cuando el usuario lo declara o el componente está identificado como tal.

Los subtítulos producen entradas auxiliares sobre el reloj de captura y pasan por el mismo detector y la misma fusión temporal. No se agregan al `TranscriptBuffer`, por lo que la transcripción visible y exportada conserva únicamente el STT local.

## Control automatizado

Una segunda ejecución de `AuralWarden.exe` puede actuar como cliente local mediante `--control-request` y `--control-output`. El cliente lee la credencial de su propia carpeta `data`, la incorpora en memoria y envía la solicitud al proceso ya abierto. El servidor procesa la orden en el hilo de la interfaz para que el estado visible, la configuración persistida y el motor permanezcan sincronizados.

La interfaz expuesta no refleja métodos internos. Cada acción tiene validación específica, límites de tamaño y una respuesta JSON estable. Esto permite que distintos agentes usen el mismo contrato sin otorgar acceso al sistema de archivos, al intérprete de comandos o a secretos de configuración.
