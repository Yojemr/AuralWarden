# Interfaz gráfica de AuralWarden 1.0.2

## Inicio

La aplicación se abre con `scripts\run-gui.ps1`. El modo `-Demo` permite comprobar la interfaz, las alertas y los clips de audio sin conectarse a Internet ni cargar Whisper.

La primera ejecución propone selección automática del modelo, motor, dispositivo y precisión, además de la hotword `ayuda` y diarización local. AuralWarden busca modelos válidos dentro de sus datos portables, el proyecto y la caché local de Hugging Face. En **Preferencias > Reconocimiento** se puede analizar el equipo, cambiar el modo de rendimiento, elegir un modelo detectado o examinar una carpeta manualmente.

## Ventana principal

Los interruptores de clips de audio y vídeo permiten pausar y reanudar la creación de clips durante el monitoreo. Los clips ya solicitados se completan; el búfer temporal de vídeo permanece activo para conservar los segundos anteriores a la siguiente detección. Si la sesión empezó sin capturar vídeo, debe activarse antes del siguiente inicio. La grabación completa, la diarización, los subtítulos y los tiempos de los clips se configuran antes de iniciar la sesión.

- **Fuente:** permite elegir un enlace o archivo, la mezcla de una salida de Windows o un micrófono. En los enlaces, AuralWarden adapta internamente YouTube, Twitch, Kick, radio y protocolos compatibles.
- **Previsualización:** muestra el nombre del directo y mantiene los fotogramas apagados hasta pulsar **Activar vista**. El modo sincronizado aplica el retraso de la ventana de transcripción.
- **Subtítulos auxiliares:** al activar la ayuda de YouTube aparece una franja fija en la parte superior de la transcripción, con las tres entradas más recientes, su hora y el estado de la pista. Si la pista todavía no existe o caduca, AuralWarden la vuelve a buscar progresivamente sin detener Whisper.
- **Transcripción:** conserva en memoria los fragmentos confirmados y los presenta agrupados en párrafos por hablante.
- **Actividad reciente:** registra alertas fusionadas y distingue la evidencia WAV y MP4 creada.
- **Recursos:** conserva un histórico corto de nivel de audio, CPU, RAM, GPU y VRAM.
- **Hotwords:** permite agregar, eliminar, ajustar el umbral y elegir opcionalmente un perfil de voz para cada término.
- **Cambios en vivo:** el detector activo recibe las ediciones de hotwords sin detener la sesión.
- **Clips y notificaciones:** configura segundos anteriores y posteriores, clips de audio o vídeo, grabaciones completas, ayuda de subtítulos, diarización, alerta de Windows y sonido.
- **Pruebas de alerta:** permite reproducir el sonido elegido o emitir el aviso completo sin iniciar una sesión.
- **Sonidos diferenciados:** amable, aviso y discreta usan archivos locales distintos y no dependen de que Windows asigne sonidos diferentes a sus eventos del sistema.
- **Presets:** aplica modos incluidos de detección, equilibrio o bajo consumo, o guarda configuraciones personales. La fuente y los dispositivos no se incorporan al preset.
- **Historial:** busca alertas anteriores por hotword, hablante, fuente o contexto y abre su clip o carpeta cuando todavía existe.
- **Escala:** Preferencias permite elegir 90, 100, 110 o 125 %; la información secundaria se oculta automáticamente cuando falta espacio horizontal.

## Hablantes

La diarización asigna etiquetas estables como `Speaker 1`. Una voz desconocida debe repetirse en al menos tres ventanas y aportar una muestra acumulada suficiente antes de recibir una etiqueta nueva. El centroide promedio se compara de nuevo con las identidades existentes, lo que evita que una ventana ruidosa cree hablantes duplicados. El botón **Hablantes** permite sustituir las etiquetas por nombres visibles después de reconocer manualmente a cada persona. Ese nombre solo pertenece a la sesión actual porque `Speaker 1` o `Speaker 2` pueden representar personas distintas en el siguiente directo. **Recordar voz** guarda voluntariamente una huella numérica local del centroide detectado; no conserva el fragmento de audio. Los perfiles guardados pueden actualizarse o eliminarse en el mismo diálogo.

En una sesión posterior, una coincidencia suficientemente clara recibe el nombre del perfil. La columna **Hablante** de las hotwords permite elegir **Cualquier hablante** o uno de esos perfiles. Al limitarla, una detección atribuida a otra voz o procedente únicamente de subtítulos no genera alerta ni clips. La identificación es probabilística y el umbral se ajusta en **Preferencias > Avanzado > Reconocimiento de perfil**.

## Párrafos y marcas de tiempo

Los fragmentos consecutivos del mismo hablante se reúnen en un párrafo. La columna izquierda muestra únicamente el momento en que comenzó ese párrafo. Al pasar el cursor o hacer clic sobre una frase concreta aparece el intervalo exacto de ese fragmento.

Se abre otro párrafo cuando cambia el hablante, existe una pausa mayor a ocho segundos o el texto alcanza un límite de duración o longitud. Si dos resultados llegan ligeramente desordenados por el solapamiento de Whisper, se conserva como inicio la hora más antigua.

## Vista previa y recursos

El título del directo aparece sobre el recuadro. Para fuentes públicas de YouTube se consulta su información pública sin claves; si no está disponible se muestra un nombre genérico.

La vista empieza apagada aunque el monitoreo ya esté activo. **Activar vista** inicia los fotogramas y **Desactivar vista** libera ese proceso. Esta elección no detiene Whisper, las hotwords, las notificaciones ni los clips. Al minimizar la aplicación, la vista también se apaga y no se reactiva sola al restaurarla.

## Ayudas y autoría

Los campos configurables muestran una explicación breve al mantener el cursor sobre ellos. El extremo inferior derecho identifica la versión ejecutada y muestra `Made by Yojemr`.

## Archivos

Sin guardado automático, el texto completo permanece temporal durante la sesión. **Guardar transcripción** exporta un TXT con párrafos continuos y una sola marca al comienzo de cada uno. El JSON automático, cuando está habilitado, mantiene cada fragmento y su tiempo exacto. Al cerrar con cambios sin guardar se ofrecen las opciones guardar, descartar o cancelar.

Los registros de coincidencias y los archivos activados se guardan dentro de la carpeta local de cada sesión. El menú **Archivos** abre por separado `clips\video`, `clips\audio`, `recordings` y `transcripts`. Si todavía no hay una sesión activa, abre el destino equivalente de la sesión más reciente. Las grabaciones completas solo se crean cuando su opción está habilitada. El búfer temporal de vídeo no es una grabación completa y se elimina al detener normalmente.

**Transcripciones** abre una biblioteca dentro de AuralWarden. La lista detecta las sesiones de la versión actual y de las carpetas portables anteriores que todavía se conserven, permite buscar por título, fecha o nombre del archivo y convierte el JSON o JSONL en párrafos con hablante y marca de tiempo. **Abrir otro archivo** permite leer de la misma forma transcripciones antiguas ubicadas fuera de esas carpetas; no las mueve ni las modifica.

Las carpetas y archivos visibles usan nombres legibles: fecha y hora, tipo de contenido, hotword y momento del directo. Si dos archivos coinciden, se añade `(2)`, `(3)`, etc.

## Segundo plano

Después de pulsar **Iniciar monitoreo**, AuralWarden puede ocultarse en la bandeja de Windows. Cerrar la ventana ofrece **Seguir en segundo plano**; la transcripción, la detección, las notificaciones y los clips continúan sin la ventana visible. La previsualización se suspende para ahorrar recursos y vuelve al restaurar la ventana. Ejecutar de nuevo el mismo `AuralWarden.exe` restaura esa instancia en lugar de crear otra sesión paralela.

El menú de la bandeja permite abrir la ventana, silenciar alertas, restaurar una salida de Windows controlada por AuralWarden, detener el monitoreo o salir. **Salir** cierra el proceso y, por tanto, termina la vigilancia.

## Fuentes locales y monitorización silenciosa

**Audio del sistema** utiliza la captura loopback de Windows y analiza toda la mezcla reproducida por la salida seleccionada. No necesita `Mezcla estéreo`, un controlador virtual ni una cuenta externa. La previsualización y los clips MP4 se deshabilitan, pero siguen disponibles la transcripción, diarización, hotwords, alertas, grabación completa y clips WAV.

**Micrófono** enumera las entradas activas conocidas por Windows. Al iniciar intenta WASAPI y, cuando corresponde, interfaces compatibles de respaldo. La apertura puede ser rechazada por permisos de privacidad, un dispositivo desconectado o el uso exclusivo desde otra aplicación; en ese caso se muestra una explicación y la sesión no continúa.

El botón **Silenciar salida** solo se habilita durante una sesión de audio del sistema y después de que exista señal. Antes de actuar muestra una advertencia que explica que el silencio afecta todas las aplicaciones de ese dispositivo. La aplicación guarda el volumen y estado originales antes de silenciar.

Una hotword restaura inmediatamente el dispositivo y lo deja encendido para escuchar el contexto posterior. El silencio no se reactiva solo. Sin una alerta, el estado original se restaura al detener, cerrar o fallar; una acción adicional en la bandeja permite restaurarlo manualmente. Si una ejecución termina abruptamente, el siguiente inicio intenta recuperar el estado guardado.

## Espera y reconexión

Una fuente que todavía no entrega audio pasa a **Esperando directo**. Un error posterior a haber recibido audio pasa a **Reconectando**. Las esperas aumentan progresivamente hasta el límite configurado en **Preferencias > Comportamiento**; **Detener** cancela cualquiera de esos estados. Un cierre limpio después de recibir audio se considera final normal y muestra **Sesión detenida**.

`data\runtime-status.json` diferencia explícitamente `application_open` de `monitoring` y se refresca periódicamente. Al restaurar la ventana, la interfaz vuelve a consultar el estado real del motor para corregir un indicador visual obsoleto.

El panel de recursos muestra el perfil adaptativo. La protección no cambia de modelo durante una frase: espera carga sostenida, reduce el haz, las segundas pasadas no esenciales o los hilos según el motor, y recupera calidad gradualmente para evitar oscilaciones.

## Control local para agentes

**Preferencias > Comportamiento > Control externo** habilita un protocolo para agentes y automatizaciones. La opción está desactivada por defecto y muestra una advertencia antes de activarse. No abre un puerto de red ni solicita una clave de ningún proveedor de IA.

Mientras AuralWarden permanezca abierto —visible o en la bandeja— un cliente autorizado puede consultar su estado, colocar un enlace HTTP/HTTPS, reemplazar las hotwords, iniciar, detener, leer una porción reciente de la transcripción o las alertas y restaurar la ventana. Los archivos y dispositivos continúan siendo selecciones manuales.

Desactivar la opción elimina la credencial local. El protocolo completo, sus límites y ejemplos están en `AGENT_CONTROL.md`.

## Alcance actual

- La notificación se emite cuando el detector crea una alerta nueva, no cuando una repetición cercana se fusiona con ella.
- Los clips MP4 están disponibles cuando se activa **Clip de vídeo**.
- Las fuentes de audio del sistema, micrófono y radio directa solo producen evidencia WAV.
- En Windows 10 se captura la mezcla completa de la salida; no se aísla una sola aplicación.
- No se integra chat ni autenticación de Twitch o Kick.
- La transcripción visible procede de Whisper local; los subtítulos de YouTube solo aportan detecciones auxiliares cuando existen.
- La distinción entre final normal e interrupción se basa en la salida de Streamlink/FFmpeg; una plataforma puede cerrar limpiamente una conexión interrumpida y hacerla parecer finalizada.
