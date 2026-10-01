# Validación del backend, fuentes de Windows, CUDA, diarización y vídeo

Última actualización: 2026-08-29

## Actualización 0.7.0

- Cien pruebas automatizadas superadas.
- La adaptación exige presión sostenida antes de entrar en modo elevado o crítico, considera RAM y VRAM y necesita varias muestras de recuperación.
- Los presets personales excluyen enlaces y dispositivos, mientras los incluidos conservan la fuente y hotwords actuales.
- El historial añade una sola alerta por evento, conserva las rutas de audio y vídeo y permite filtrar desde la interfaz.
- Los botones de evidencia de actividad reciente emiten la ruta correcta para audio o vídeo.

## Actualización 0.5.0

- 80 pruebas automatizadas superadas.
- `yt-dlp` 2026.08.19 localizó una pista automática en español en el enlace real de YouTube usado para desarrollo.
- Lectura JSON3 y WebVTT segmentada, frases repartidas entre entradas de subtítulos y fusión con el detector principal comprobadas.
- Los subtítulos auxiliares no se incorporan a la transcripción visible ni exportada.
- Grabación completa MP4 creada desde la misma captura segmentada; audio, vídeo y limpieza normal comprobados.
- Diario incremental recuperable comprobado para sesiones interrumpidas y excluido en cierres normales.
- Migración de esquema, preferencias y modelos mediante enlaces físicos comprobada sin copiar sesiones ni transcripciones.

## Actualización 0.4.1

- 74 pruebas automatizadas superadas.
- Las hotwords compuestas se detectan aunque sus palabras se repartan entre fragmentos consecutivos; la transcripción visible conserva su estructura original.
- Una coincidencia entre fragmentos produce una sola alerta y programa correctamente el clip con contexto anterior.
- Las voces nuevas requieren confirmación entre ventanas antes de crear una etiqueta permanente.
- Los turnos cortos o sin embedding fiable reutilizan una identidad probable y no incrementan artificialmente el número de hablantes.
- El número esperado de hablantes limita las identidades globales de la sesión y ya no fuerza grupos dentro de cada ventana de seis segundos.
- El solapamiento temporal no prevalece cuando contradice una huella de voz fiable.
- El ejecutable portable confirmó Qt, FFmpeg interno, captura de Windows, faster-whisper, CUDA `float16`, sherpa-onnx, tres salidas de audio y dos micrófonos detectables.
- La interfaz 0.4.1 se renderizó correctamente fuera de pantalla y la carpeta final quedó limpia de sesiones de validación.

## Entorno

- Windows 10.
- Python 3.12.13 en `.venv`.
- NVIDIA GeForce RTX 3060 con 12 GB de VRAM.
- FFmpeg 8.1.2.
- Streamlink 8.5.0.
- PyAudioWPatch 0.2.12.8 y pycaw 20251023.
- faster-whisper 1.2.1.
- CTranslate2 4.8.1.
- sherpa-onnx 1.13.6.
- cuBLAS 12.9.2.10 y cuDNN 9.24.0.43 instalados en `.venv`.
- Modelo local `large-v3-turbo` de 1.621.667.708 bytes.
- Modelos ONNX locales de diarización: segmentación de 5.992.913 bytes y embeddings de 39.593.761 bytes.

## Resultados

- 56 pruebas automatizadas superadas.
- Autocomprobación del portable superada con Qt, FFmpeg interno, CUDA `float16`, faster-whisper, CTranslate2, sherpa-onnx, Streamlink, PyAudioWPatch y pycaw.
- Tres sonidos WAV PCM mono diferenciados y presentes dentro del paquete.
- Interfaz 0.3.1 renderizada correctamente en modo fuera de pantalla desde el ejecutable reorganizado.
- Tamaño reducido de 2.498,0 MB a 2.317,9 MB sin retirar cuBLAS ni cuDNN.
- Tres salidas loopback y dos entradas WASAPI enumeradas en la máquina de desarrollo.
- Captura real de la salida predeterminada comprobada durante un segundo con 32.000 bytes PCM mono de 16 bits y 16 kHz, sin guardar contenido.
- Reloj de la captura comprobado durante silencio digital mediante inserción de PCM silencioso.
- Remuestreo estéreo de 48 kHz a mono 16 kHz comprobado con una señal determinista.
- Silencio reversible, restauración original, recuperación tras interrupción y activación permanente por hotword comprobados con un endpoint simulado.
- Selector de fuente, medidor de audio, controles deshabilitados y advertencia de monitorización silenciosa revisados visualmente.
- Espera de una fuente sin audio y posterior conexión comprobadas.
- Reconexión tras una interrupción comprobada sin reiniciar la línea temporal.
- Límite configurable de intentos y espera cancelable comprobados.
- Fusión de manifiestos de vídeo de varios intentos sobre un reloj global comprobada.
- Estados `waiting`, `reconnecting` y `stopped` comprobados en la interfaz.
- `runtime-status.json` comprobado para diferenciar aplicación abierta de monitoreo activo.
- Pruebas manuales configurables de sonido y aviso completo comprobadas.
- Nombres legibles comprobados para sesión, audio completo, transcripción, WAV y MP4.
- Agrupación de fragmentos en párrafos comprobada sin modificar las entradas internas.
- Exportación TXT continua y tiempos interactivos por fragmento comprobados.
- Previsualización manual comprobada sin inicio automático de FFmpeg.
- Título público de YouTube, ayudas contextuales, autoría y dimensiones de hotwords comprobados.
- Detección automática comprobada de `large-v3-turbo` desde el proyecto y desde una carpeta ejecutable versionada.
- Apertura comprobada de las carpetas separadas para clips de vídeo, clips de audio y transcripciones.
- Conversión real de WAV estéreo de 48 kHz a PCM mono de 16 kHz.
- Captura HLS remota mediante Streamlink y FFmpeg durante dos segundos.
- Complemento de YouTube presente en Streamlink.
- CUDA detectada por CTranslate2 y `float16` disponible.
- Simulación completa con transcripción, dos hotwords, registro y dos clips WAV.
- Inferencia CUDA real sobre un audio oficial de prueba de Whisper de 11 s.
- Transcripción CUDA completada en 2,858 s, con factor de tiempo real 0,260.
- Aumento observado de VRAM de 1.807 MB a 4.031 MB durante la carga e inferencia.
- Reconocimiento correcto de las tres frases de control configuradas.
- Flujo integrado completado con dos coincidencias de `your country`, fusionadas en un solo evento.
- Clip de evidencia WAV válido: PCM mono de 16 bits, 16 kHz y 4 s.
- Paquete portable completo validado con el mismo modelo, alerta, clip y diarización sin utilizar el intérprete de `.venv`.
- Tamaño observado del paquete portable 0.2.0 con CUDA, sherpa-onnx y FFmpeg, sin modelos: 2.615.628.610 bytes; ZIP final de 1.549.631.083 bytes.
- Captura simultánea de PCM y segmentos MPEG-TS sobre un vídeo local controlado de ocho segundos.
- Clip MP4 de dos segundos creado a partir de una hotword simulada con un segundo anterior y uno posterior.
- Presencia de pistas de vídeo y audio confirmada mediante FFprobe.
- Búfer `.video-buffer` eliminado al finalizar normalmente la sesión.

## Prueba real de YouTube en español

- El 3 de septiembre de 2026 se comprobó durante un directo que YouTube exponía los subtítulos visibles como una única pista automática identificada internamente como `en`, en formato WebVTT y protocolo M3U8, aunque el contenido hablado y mostrado era español.
- El resolvedor actualizado seleccionó esa pista como respaldo seguro y recuperó de forma incremental únicamente los segmentos nuevos, con tiempos alineados al directo.

- Fuente: `https://www.youtube.com/watch?v=Ygt2rwVusTs`.
- Duración solicitada: 120 s; audio capturado: 127 s.
- Estado final de sesión: `stopped`, sin errores de Streamlink, FFmpeg ni CUDA.
- 48 fragmentos de transcripción confirmados.
- Hotword configurada: `ayuda`, umbral 88.
- Coincidencia exacta al 100 % en `buenisima ayuda ayuda levanta la escopeta...`.
- Marca temporal de la palabra dentro del directo monitorizado: 69,72 s.
- Un evento creado, sin fusiones adicionales ni falsos positivos observados en la transcripción.
- Clip WAV de 25 s: 10 s de pre-roll y 15 s de post-roll, PCM mono de 16 bits a 16 kHz.
- La hotword volvió a detectarse al 100 % al reprocesar el clip con las ventanas solapadas del motor.

Una pasada única sobre los 25 s completos no conservó la hotword, mientras que el procesamiento por ventanas sí lo hizo. Este resultado respalda mantener ventanas cortas y solapadas en el flujo en vivo para minimizar falsos negativos.

## Perfil 0.1.1 y diarización

- Perfil predeterminado cambiado de 8 s/1 s a 6 s/2 s.
- VAD configurado con umbral 0,35, voz mínima de 100 ms, silencio de 500 ms y margen de 350 ms.
- Segunda pasada activada por confianza menor a 0,62, candidato dudoso o audio no silencioso sin texto.
- El clip real produjo 93 palabras con probabilidad individual antes de estabilizar duplicados.
- Las dos apariciones de `ayuda` tuvieron probabilidades 0,867 y 0,991.
- La marca de la alerta se corrigió al final de la primera palabra: 6,47 s dentro del clip.
- La diarización automática estabilizó cuatro etiquetas sobre el clip de 25 s.
- La monitorización combinada de YouTube solicitada durante 45 s capturó 54 s, terminó en estado `stopped` y produjo 17 entradas, 119 palabras y tres hablantes.
- Esa prueba combinada no creó alertas porque `ayuda` no apareció en el intervalo transcrito.

## Comparación reproducible sobre el mismo clip

| Perfil | Ventana/solapamiento | Tiempo de proceso | Entradas | Segunda pasada | `ayuda` |
|---|---:|---:|---:|---:|---:|
| Anterior | 8 s / 1 s | 5,937 s | 5 | 0 | detectada |
| Alta recuperación | 6 s / 2 s | 7,357 s | 8 | 2 | detectada |

Ambos perfiles procesaron el mismo clip de 25 s más rápido que tiempo real. El perfil nuevo conservó contexto adicional y eliminó las repeticiones principales mediante estabilización temporal. Una medición de precisión absoluta todavía requiere audio etiquetado manualmente.

## Alcance no validado

- No se realizó todavía una prueba prolongada de varias horas ni una evaluación cuantitativa con corpus etiquetado en español.
- Los clips MP4 se validaron con una fuente local controlada; queda pendiente una prueba prolongada sobre YouTube.
- El micrófono Realtek figura activo y los permisos globales están habilitados, pero su controlador rechazó la apertura mediante WASAPI, DirectSound y MME en esta máquina. El flujo de error y los intentos de respaldo están comprobados; falta validar captura efectiva con otro micrófono.
- Twitch, Kick y radio están implementados mediante los adaptadores disponibles, pero falta una sesión prolongada real por cada plataforma.
