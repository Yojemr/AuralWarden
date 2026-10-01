# Privacidad

## Procesamiento

La captura necesita conectarse a la fuente y la descarga inicial de los modelos necesita Internet. El reconocimiento, la diarización, las hotwords, el búfer, los clips y los registros se procesan localmente sin APIs remotas de reconocimiento o inteligencia artificial.

Para mostrar el nombre de un directo público de YouTube, la interfaz consulta el endpoint público oEmbed de YouTube usando únicamente el enlace que el usuario ya indicó. No utiliza clave, cuenta ni servicio de IA remoto; si la consulta falla se muestra un título genérico. La previsualización permanece apagada hasta que el usuario la activa.

Los enlaces públicos de Twitch y Kick se resuelven mediante Streamlink sin integrar chat, cuentas o credenciales. Las fuentes locales de micrófono y audio del sistema no se envían por Internet.

## Fuentes de Windows

El modo **Audio del sistema** recibe la mezcla completa del dispositivo seleccionado. Puede incluir sonidos de otras aplicaciones además de la fuente que motivó la sesión. La interfaz lo identifica expresamente y la captura solo comienza al pulsar **Iniciar monitoreo**.

La monitorización silenciosa modifica temporalmente el silencio del dispositivo completo. Requiere confirmación, guarda únicamente identificador, nombre, volumen y estado anteriores en `silent-audio-state.json`, y elimina ese archivo al restaurar. No contiene audio ni texto. Una hotword activa la salida y la deja encendida; al detener sin alerta se recupera el estado original.

El modo **Micrófono** puede captar conversaciones cercanas. Debe usarse únicamente con las autorizaciones y avisos aplicables. La grabación completa continúa desactivada por defecto y los clips conservan solo los intervalos configurados.

## Transcripción

La transcripción visible permanece en memoria durante la sesión, pero AuralWarden mantiene además un diario incremental local dentro de `data/sessions` para poder recuperarla después de un cierre inesperado. El archivo TXT o JSON de consulta permanente solo se exporta cuando se activa o confirma el guardado. Las coincidencias sí se registran por defecto con hora, contexto y confianza para conservar la finalidad principal de las alertas.

Los títulos, autores y subtítulos recibidos de plataformas se muestran como texto inerte. No se interpretan como HTML ni pueden solicitar imágenes locales o de red desde la interfaz.

`alert-history.json` mantiene localmente un índice de hasta 1.000 alertas con hotword, hablante atribuido, fuente, contexto y rutas de evidencia. Vaciar el historial no elimina clips ni transcripciones. Los presets personales se guardan en `presets.json` y excluyen el enlace de origen, el título y los identificadores de dispositivos.

## Búfer y clips

El búfer PCM conserva únicamente la ventana reciente configurada en RAM y descarta automáticamente el contenido anterior. Cuando se detecta una hotword puede guardarse un clip WAV con el intervalo anterior y posterior.

Los clips MP4 son opcionales. Al activarlos, FFmpeg mantiene segmentos audiovisuales breves en una carpeta `.video-buffer` dentro de la sesión. El búfer se limita por tiempo, los segmentos antiguos se descartan y la carpeta temporal se elimina al detener normalmente. Los clips terminados se conservan por separado en `clips/video/` y `clips/audio/`. Un cierre abrupto de Windows o del proceso puede dejar fragmentos temporales, que pueden eliminarse junto con `.video-buffer` cuando AuralWarden no esté ejecutándose.

## Hablantes

La diarización utiliza modelos ONNX locales de sherpa-onnx. No consulta bases externas: genera etiquetas neutrales como `Speaker 1`. Los nombres visibles solo se agregan cuando el usuario los asigna manualmente.

**Recordar voz** es voluntario. Guarda en `speaker-profiles.json` un nombre elegido por el usuario y un vector numérico normalizado obtenido por el modelo local; no guarda la muestra de audio usada para calcularlo. Esa huella se utiliza únicamente para comparar voces dentro de AuralWarden, puede producir confusiones y no debe considerarse una identificación personal infalible. Los perfiles pueden eliminarse desde **Hablantes** y nunca se incluyen en Git.

## Audio completo

La grabación completa está desactivada por defecto. Cuando se activa, se escribe incrementalmente dentro de la carpeta local de la sesión. Activar clips MP4 no activa por sí solo una grabación audiovisual completa.

## Datos locales

Las sesiones normales se guardan en `%LOCALAPPDATA%\AuralWarden`. El modo portable usa `data/` junto al proyecto o ejecutable. Esas rutas, además de modelos, cookies, claves y variables privadas, están excluidas de Git.

En el primer inicio, el asistente puede descargar modelos desde Hugging Face y, para separar hablantes, desde GitHub. La descarga no utiliza credenciales ni cookies del navegador y verifica revisiones, tamaños y SHA-256 fijados. Esos proveedores reciben la dirección IP de la conexión. El audio, las hotwords y la transcripción no se envían durante este proceso.

`runtime-status.json` se guarda únicamente en esa carpeta local. Contiene versión, identificador del proceso, fuente configurada sin usuario, contraseña, consulta ni fragmento, ruta de la sesión, estado y hora de actualización; no contiene audio, transcripción, hotwords, claves ni credenciales. Se refresca mientras la aplicación permanece abierta para distinguir una ventana abierta de un monitoreo realmente activo.

Un enlace firmado de radio, HLS u otra plataforma puede contener credenciales temporales en su consulta. AuralWarden necesita conservar el enlace completo en `settings.json` para volver a usar la fuente, por lo que ese archivo es privado y está excluido de Git. Los estados y diagnósticos externos muestran una versión depurada del enlace.

## Control local para agentes

El control local está desactivado por defecto. Al habilitarlo se crea `local-control.json`, que contiene una credencial aleatoria propia de AuralWarden y no una clave de OpenAI, Telegram ni otro servicio. La comunicación usa el mecanismo local de instancia única de Windows y no abre un puerto de red.

Las órdenes posibles se limitan a consultar capacidades y estado, insertar un enlace HTTP/HTTPS, reemplazar hotwords, iniciar o detener, restaurar la ventana y leer hasta 200 fragmentos o alertas recientes. No existe una orden para ejecutar programas, explorar rutas, leer configuraciones o recuperar credenciales. Las alertas devueltas indican si hay clips pero omiten sus rutas.

`local-control-audit.json` conserva hasta 500 resultados con hora, acción y código. No registra argumentos, enlaces, hotwords, transcripción ni credenciales. Al desactivar el control se elimina la credencial; el historial de auditoría permanece local para diagnóstico.

El límite de confianza es la cuenta local de Windows: un programa ejecutado como el mismo usuario y con acceso a la carpeta portable podría usar la credencial mientras la opción esté activa. Debe dejarse desactivada en equipos compartidos o cuando no se necesite.
