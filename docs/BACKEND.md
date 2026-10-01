# Backend y eventos

## Ciclo de una sesión

`MonitoringEngine` administra los estados `starting`, `running`, `waiting`, `reconnecting`, `stopping`, `stopped` y `failed`. Puede ejecutarse en primer plano o en un hilo de trabajo.

Cada sesión crea una carpeta con:

- `session.json`: fuente, estado, fechas y estadísticas.
- `events.jsonl`: coincidencias creadas o fusionadas.
- `clips/audio/`: clips WAV asociados a detecciones.
- `clips/video/`: clips MP4 asociados a detecciones.
- `.video-buffer/`: segmentos temporales mientras los clips MP4 están habilitados; se elimina al finalizar normalmente.
- `recordings/AAAA-MM-DD_HH-MM-SS - Audio completo.wav`: solo cuando se solicita audio completo.
- `transcripts/AAAA-MM-DD_HH-MM-SS - Transcripcion.txt` y `.json`: solo cuando se activa el guardado.

La carpeta de sesión usa `AAAA-MM-DD_HH-MM-SS - Título del directo`. Los clips añaden tipo, hotword y tiempo transcurrido; las colisiones se resuelven con sufijos `(2)`, `(3)`, etc.

## Eventos para la interfaz

`EventBus` publica mensajes con estos tipos:

- `state`: transición del ciclo de sesión.
- `transcript`: fragmento confirmado, hablante, palabras, probabilidades, tiempos y hotwords.
- `hotword`: coincidencia, confianza, contexto y estado de fusión.
- `clip`: ruta, tipo de medio y estado completo o parcial del archivo creado.
- `resource`: CPU, RAM, GPU, VRAM, red y perfil de carga.
- `error`: fallo recuperable o terminal.
- `info`: espera, reconexión, conexión recuperada, nivel de audio y final limpio de la fuente.

La cola está limitada para evitar crecimiento indefinido durante sesiones largas. Los consumidores lentos conservan siempre los eventos más recientes.

`AdaptiveLoadController` evalúa CPU, GPU, RAM y VRAM. Exige varias muestras consecutivas para entrar en carga elevada o crítica y aplica histéresis antes de recuperar calidad. `faster-whisper` reduce el haz y el motor omite segundas pasadas no esenciales; `whisper.cpp` limita hilos. El modelo no se descarga ni se recarga durante una sesión.

## Presentación de la transcripción

Los eventos internos y la exportación JSON conservan cada fragmento por separado. La interfaz y el TXT agrupan fragmentos continuos del mismo hablante en párrafos, con límites de pausa, duración y longitud. Esta presentación no modifica la detección, las hotwords ni los tiempos originales.

## Evidencia audiovisual

Cuando los clips MP4 están habilitados, la misma ejecución de FFmpeg entrega PCM para Whisper y conserva segmentos audiovisuales de dos segundos. Al vencer el post-roll, un trabajador independiente concatena solo los segmentos necesarios. Primero intenta conservar los códecs originales y, si el contenedor no lo permite, usa una recodificación de compatibilidad. La transcripción continúa mientras se construye el archivo.

## Reconexión

`ReconnectingCapture` crea nuevos conductos Streamlink/FFmpeg cuando una fuente remota falla y desplaza sus tiempos para mantener un reloj continuo. Los manifiestos audiovisuales de cada intento se fusionan sobre ese mismo reloj. Una fuente sin audio entra en `waiting`; un error después de audio entra en `reconnecting`; un EOF limpio después de audio finaliza la sesión normalmente. El `stop_event` interrumpe también la espera progresiva.

La interfaz publica atómicamente `runtime-status.json`. Sus campos `application_open` y `monitoring` son independientes y evitan deducir el estado de una sesión únicamente por la existencia del proceso.

## Captura local de Windows

`WasapiPcmCapture` abre una salida loopback o una entrada física, reduce todos los canales a mono y remuestrea al formato común de 16 kHz. En una salida que deja de entregar paquetes durante el silencio se insertan bloques PCM silenciosos para conservar el reloj real. Los niveles RMS se publican como eventos `info/audio_level`.

`SilentMonitoringManager` guarda atómicamente el estado del endpoint antes de silenciarlo. La restauración normal recupera exactamente volumen y silencio; la restauración provocada por una hotword garantiza que la salida quede activa y usa un volumen mínimo audible si el original era cero. El archivo de recuperación permite revertir el silencio después de un cierre inesperado.

## Segunda pasada

El detector evalúa todas las hotwords. El motor repite una ventana cuando existe un candidato cercano, la confianza cae por debajo del umbral o hay audio no silencioso sin texto. La pasada de comprobación omite texto de guía y mantiene los controles de voz del motor; se elige según calidad y probabilidades, sin premiar que contenga una hotword. La comparación aproximada continúa disponible y una palabra real no se bloquea solo por figurar en la configuración.

La lectura PCM utiliza un productor independiente y una cola limitada a 120 segundos. Si la inferencia no sigue el ritmo, la interfaz muestra el retraso; al agotarse la cola se descartan los bloques más antiguos y se comunica esa pérdida. La grabación completa recibe el audio antes del descarte. Las discontinuidades vacían el contexto y se conservan las marcas de los bloques restantes.

Los índices CSV de vídeo son registros de solo adición, leídos desde la última fila completa. La caché en memoria y los segmentos de clips caducan según el búfer configurado. El pequeño registro de metadatos puede crecer durante la sesión; la grabación completa conserva los segmentos intencionadamente. Un clip fallido conserva los segmentos disponibles para recuperación.

## Perfil de alta recuperación

El perfil predeterminado usa ventanas de 6 s con 2 s de solapamiento, VAD tolerante y estabilización entre ventanas. El contexto y el vocabulario influyen en Whisper, pero no crean alertas. Las probabilidades por palabra permiten ubicar una coincidencia en su instante real.

## Diarización

`SherpaOnnxDiarizer` procesa cada ventana en CPU, agrupa turnos y calcula embeddings de voz. Los centroides se conservan durante la sesión para mantener etiquetas estables. Una identidad desconocida permanece provisional hasta repetirse en tres ventanas y acumular al menos tres segundos de voz; su embedding promedio se compara otra vez con los centroides existentes antes de crear una etiqueta. Las palabras de Whisper se reparten por sus marcas temporales y un fragmento puede dividirse cuando cambia el hablante. El número de hablantes puede detectarse automáticamente o configurarse como límite global.

Los perfiles voluntarios reutilizan esos embeddings: `speaker-profiles.json` conserva vectores normalizados y nombres asignados por el usuario. Un perfil solo reemplaza la etiqueta neutral si supera su umbral independiente. Las hotwords con `speaker_profile` comprueban la identidad comparada, no solo la etiqueta visible, antes de crear el evento, la notificación o los clips; los subtítulos no satisfacen un filtro de voz. Una frase restringida debe mantener el mismo hablante entre fragmentos.

## Adaptación de recursos

El muestreo de recursos clasifica el equipo como `normal`, `constrained` o `critical`. En los dos últimos perfiles se reduce el haz de la primera pasada. En carga crítica se omiten los rescates generales de baja confianza, pero se conserva la segunda pasada ante candidatos de hotword.

## Comprobaciones

```powershell
.\scripts\run.ps1 doctor
.\scripts\run.ps1 simulate
.\scripts\test.ps1
```
