# Funciones y vías de acceso

El catálogo cubre AuralWarden 1.6.0. Consulta `capabilities` para conocer las órdenes de la instancia activa. «Interfaz» identifica funciones disponibles mediante la ventana de AuralWarden.

## Órdenes locales

El ayudante `../scripts/Invoke-AuralWarden.ps1` recibe `-Action` y un hashtable `-Parameters`. No incluyas campos `token`, `protocol_version` ni secretos. La autenticación permanece dentro del ejecutable.

| Acción | Parámetros | Efecto y precaución |
|---|---|---|
| `capabilities` | Ninguno | Acciones y límites de la instancia. |
| `status` | Ninguno | Versión, estado, fuente redactada, tiempo, hotwords y contadores. Contiene información personal que solo debe consultarse para la tarea. |
| `set_source` | `source`: URL HTTP/HTTPS o demo local | Cambia a fuente de enlace para la próxima sesión. Rechaza una sesión activa. No selecciona archivos, micrófono ni ventana. |
| `set_hotwords` | `hotwords`: lista de textos u objetos | Sustituye toda la lista y actualiza el monitor activo. Un objeto permite `phrase`, `threshold`, `enabled`, `speaker_profile`. No inventar perfiles de voz. |
| `start` | Ninguno | Solicita iniciar con la configuración visible. No activa por sí solo opciones de vídeo/audio que estén apagadas. |
| `stop` | Ninguno | Solicita detener/finalizar y recuperar el audio cuando corresponda. Comprobar estado final y exportación pendiente. |
| `transcript` | `limit`, 1–200; predeterminado 50 | Fragmentos recientes, hablante, tiempos, texto, confianza y hotwords. Preferir 10–25. No es una descarga de todo el archivo. |
| `alerts` | `limit`, 1–200; predeterminado 25 | Alertas históricas recientes sin rutas de evidencia. Pueden incluir sesiones anteriores; contrastar tiempos. |
| `show` | Ninguno | Restaura la ventana, no inicia monitoreo. |
| `list_windows` | `application` | Devuelve IDs de ventanas del ejecutable solicitado, válidos durante dos minutos o hasta la siguiente consulta. |
| `list_audio_devices` | `kind` | Enumera dispositivos de `system_audio` o `microphone`. |
| `select_windows_source` | `kind`, `window_id` y/o `device` | Con el monitor detenido, elige `application_audio` (ID), `window_capture` (ID y salida), `system_audio` (salida) o `microphone` (entrada). |
| `configure_session` | `options` | Con el monitor detenido, ajusta `diarization`, `save_full_audio`, `save_full_video`, `audio_clips`, `video_clips`, `clip_pre_seconds` (0–60) y `clip_post_seconds` (0–120). Las opciones omitidas se conservan. |
| `set_stop_timer` | `duration_seconds` o `stop_at_epoch` | Programa la detención por duración de hasta siete días o fecha Unix futura. Sin campos, cancela. |
| `create_clip` | Ninguno | Solicita un clip usando el búfer y las preferencias de la sesión activa. |
| `save_transcript` | Ninguno | Exporta un TXT nuevo en la carpeta de transcripciones y devuelve el nombre generado. |
| `separate_audio` | `application`, `confirmed: true` | Solicita enviar al VB-CABLE la aplicación monitoreada. |
| `restore_audio` | Ninguno | Solicita restaurar la salida original de la aplicación. |

## Separar y restaurar el audio

Usa `list_windows -Parameters @{application='chrome'}` para localizar el objetivo. Si hay varias ventanas y la elección importa para grabar vídeo, usa el título para confirmar la selección. Envía `select_windows_source -Parameters @{kind='application_audio';window_id='<id>'}` con el monitor detenido. Configura las preferencias pedidas y usa `start` si el usuario solicitó monitorear. Cuando llegue señal, usa `separate_audio -Parameters @{application='chrome';confirmed=$true}` con autorización para cambiar el audio de toda la aplicación. El enrutamiento requiere un VB-CABLE estándar disponible y afecta a todas sus pestañas y ventanas. `restore_audio` devuelve la salida original usando el auxiliar de AuralWarden.

Consulta `status.audio_route.phase` después de cada cambio. `active` confirma la separación y `restored` confirma la restauración. `requested` y `preparing` indican que el cambio está en curso. `waiting` y `pending` indican restauración pendiente. Con `failed`, informa el error. Una hotword, la detención o el cierre también solicitan la restauración.

Ejemplo de hotword avanzada:

```powershell
-Action set_hotwords -Parameters @{hotwords=@(@{phrase='palabra clave';threshold=88;enabled=$true;speaker_profile=''})}
```

El canal está vinculado a la carpeta de datos, cuenta y sesión de Windows. Una instalación que reutiliza datos puede compartir canal con otra; ante ambigüedad pide la selección de instancia. No cambies `AURALWARDEN_DATA_DIR` para acceder a una sesión ajena. La credencial persistente nunca se pone en la solicitud. Las solicitudes se eliminan al terminar el cliente; evita URL privadas en la línea de comandos, historial o respuestas públicas.

## Fuentes, captura, alertas y segundo plano

| Función | Acceso real | Detalles |
|---|---|---|
| YouTube, Twitch, Kick, radio y enlaces compatibles | IPC `set_source` + `start`; interfaz | Streamlink/FFmpeg y motor local según soporte de la fuente; no garantiza acceso a servicios privados. |
| Archivo local | Interfaz; CLI `monitor` | Elegir el archivo explícito. `set_source` no admite rutas locales. |
| Audio general del PC y micrófono | IPC `list_audio_devices` y `select_windows_source`, interfaz | Loopback o entrada elegida. |
| Audio de una aplicación | IPC `list_windows` y `select_windows_source`, interfaz | Captura el proceso y sus descendientes. La selección se renueva al abrir. |
| Ventana + audio o vídeo de una aplicación | IPC `select_windows_source` y `configure_session`, interfaz | Prepara vídeo antes del inicio y mantén la ventana sin minimizar. |
| Separar audio con VB-CABLE y restaurar la salida | IPC `separate_audio` y `restore_audio`, interfaz | Requiere consentimiento para la aplicación completa y un cable instalado. |
| Hotwords y frases fuzzy, hablante opcional | IPC `set_hotwords`; interfaz | El umbral y perfil los decide el usuario. Una coincidencia no prueba por sí sola que una frase se dijo; contrastar audio si hay duda. |
| Clips automáticos de audio/vídeo y sus tiempos | IPC `configure_session`, interfaz, CLI `monitor` | Configura el vídeo antes de iniciar la captura. |
| Audio y vídeo completos opcionales | IPC `configure_session`, interfaz, CLI `monitor` | Activa la grabación completa solo si se solicita. |
| Sonidos, notificaciones y pruebas | Interfaz | Probar sonido solo si se pidió, especialmente mientras el usuario escucha otra aplicación. |
| Monitoreo minimizado, bandeja, vista previa bajo demanda | Interfaz; IPC `show`, `status`, `start`, `stop` | Cerrar la ventana puede mantener la sesión; salir del proceso la termina. No confundir ventana oculta con detención. |
| Espera de directo, reconexión progresiva, cancelación | Interfaz; IPC `status`/`stop` | Consultar estado y límites configurados; no reiniciar el proceso porque temporalmente no llegue texto. |

## Reconocimiento, organización y sesiones

| Función | Acceso real | Referencia del proyecto |
|---|---|---|
| Modelos locales, instalación explícita, CPU/CUDA, rendimiento adaptativo | Preferencias; CLI `doctor`, `download-model` | `docs/HARDWARE.md`, `docs/FIRST_RUN.md`. No fijar un equipo como requisito universal ni instalar componentes sin permiso. |
| Contexto y vocabulario, VAD, silencios y segunda pasada | Preferencias; opciones CLI `monitor`/`compare-audio` | `docs/BACKEND.md`. No introducir texto de contexto en la transcripción como evidencia. |
| Subtítulos auxiliares YouTube y fusión temporal | Interfaz; CLI `monitor` | `docs/GUI.md`, `docs/BACKEND.md`. Visibilidad separada de Whisper, disponibilidad dependiente de la fuente. |
| Diarización, nombres manuales, perfiles voluntarios y alertas por hablante | IPC para activar diarización y configurar alertas, interfaz para nombres y perfiles, CLI para diarización | `docs/GUI.md`. Las identidades son estimaciones. |
| Guardar/exportar transcripción completa | IPC `save_transcript`, interfaz, backend con salida explícita | IPC `transcript` devuelve fragmentos recientes. |
| Abrir transcripciones anteriores, búsqueda literal y marcas de tiempo | Biblioteca, Ctrl+F | `docs/GUI.md`; `auralwarden.transcript_archive` para lectura offline. No hace falta mostrar todo el texto en el chat. |
| Revisión junto a vídeo/audio, clic en frase, tiempo, intervalo y exportación | Biblioteca; backend offline `media_review` | `docs/RELEASE_NOTES_1.5.0.md`. Sin reproducción automática; desfase para archivos sin índice; rechazar cortes desconocidos. |
| Recuperación de sesión interrumpida | Interfaz, diarios locales | `docs/GUI.md`. No reanudar automáticamente una clase o micrófono al consultar estado. |
| Marcadores y clips manuales | IPC `create_clip` para clips, menú Momentos, bandeja | `docs/GUI.md`. Ctrl+M marca un instante y Ctrl+Alt+C solicita un clip desde AuralWarden. |
| Temporizador de detención | IPC `set_stop_timer`, menú Temporizador | `docs/GUI.md`. El temporizador pertenece a la instancia activa. |
| Presets, historial y abrir carpetas | Interfaz | `docs/GUI.md`. El historial de alertas sí admite lectura IPC limitada. |
| Inventario de almacenamiento, Papelera, migración/reutilización de datos | Interfaz con confirmación | `docs/INSTALLATION.md`, `docs/PRIVACY.md`. No borrar carpetas/versiones como parte de una consulta. |
| Avisos, licencias, autoría, actualización portable/instalada | Interfaz y documentación | `LICENSE`, `NOTICE`, `docs/THIRD_PARTY_NOTICES.md`, `docs/INSTALLATION.md`. No aceptar condiciones ni publicar por cargar esta skill. |

## Backend y archivos guardados

Si existe un checkout verificado, usa su `.venv/Scripts/python.exe -m auralwarden --help`. El EXE gráfico no equivale a la CLI del backend. `doctor --json` es diagnóstico; `simulate --output <carpeta nueva>` usa datos sintéticos, pero genera archivos. `capture-test` captura la fuente indicada y requiere autorización igual que `monitor`. `download-model`, `download-diarization-models` y descargas implícitas requieren permiso; comprueba `--help` de esa versión antes de usarlas.

`monitor` admite modelo/dispositivo/precisión/idioma, contexto, vocabulario, ventana/solape, búfer, pre/post, hotwords/umbral, diarización/modelos/nombres, audio/vídeo completo, clips de vídeo, ayuda YouTube y guardado de transcripción. Usa `--offline` y un modelo local cuando ya esté disponible; no arranques un segundo monitor para suplir un ajuste inaccesible durante una sesión activa.

Para un clip offline autorizado, `auralwarden.media_review` expone `probe_media(path)`, `load_timeline(path)`, `MediaTimeline.interval(inicio_sesion, fin_sesion, desfase)` y `export_interval(origen, destino_nuevo, inicio_archivo, fin_archivo, session_start=...)`. Este acceso requiere el entorno del proyecto; conserva el origen, comprueba el índice y verifica duración/resultado. No decodifiques todo un vídeo para consultar su duración. No uses una operación de exportación como prueba sin permiso para generar el archivo.

Los diagnósticos ocultos `--self-check*` son de desarrollo, no órdenes de usuario. Algunos prueban captura, hardware o rutas de audio: no ejecutarlos todos por rutina. Para esta skill bastan descubrimiento, esquema y una instancia sintética aislada cuando esté autorizada.
