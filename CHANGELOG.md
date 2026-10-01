# Historial de cambios

El proyecto utiliza versionado semántico: `MAJOR.MINOR.PATCH`.

## [Unreleased]

### Planned

- Correcciones posteriores basadas en informes reproducibles de otros equipos.
- Validación y empaquetado opcional de un componente `whisper.cpp` con Vulkan para hardware AMD e Intel.

## [1.0.2] - 2026-09-30

### Fixed

- La captura PCM se lee en un hilo independiente de la inferencia. Una cola de 120 segundos limita la RAM y comunica retrasos o pérdida por saturación; la grabación completa de audio recibe los bloques antes de ese límite.
- La segunda pasada se elige por calidad del reconocimiento y probabilidades, sin premiar que contenga una hotword. Las palabras reales con buena evidencia no se bloquean por figurar en el contexto configurado.
- La deduplicación requiere solapamiento temporal y conserva palabras nuevas; las hotwords eliminadas durante una inferencia se vuelven a comprobar antes de emitir alertas o solicitar clips.
- Los perfiles de voz solo se atribuyen cuando la comparación correspondiente supera el umbral. Una frase restringida a un hablante no se reconstruye con palabras de otro hablante; los nombres manuales se aplican también a fragmentos futuros.
- Los intervalos de clips quedan fijados al solicitarlos, aunque la fusión actualice una detección. El audio usa únicamente el intervalo pedido y señala preámbulos o finales incompletos.
- Los clips MP4 comprueban que haya fotogramas decodificables y utilizan conversión de respaldo cuando la copia directa no los produce. Se espera cobertura de segmentos antes de finalizar un clip.
- Los manifiestos de vídeo se leen incrementalmente. Se conservan segmentos conocidos durante lecturas parciales y se utiliza un registro de solo adición para evitar conflictos de reemplazo concurrente en Windows.
- La cola de clips tiene un límite y comunica saturación. Los fallos conservan segmentos recuperables; las reconexiones incorporan también el último segmento del intento anterior.
- El cierre espera al trabajador y al fragmento final antes de ofrecer guardar la transcripción. Los errores de inicio, escritura de diagnóstico o finalización mantienen un estado de fallo coherente.
- La cancelación de captura se sincroniza con el arranque de FFmpeg. Los códigos de salida distintos de cero se detectan aunque no haya texto de error.
- Los subtítulos evitan reemitir el historial al rotar su caché, reinician la deduplicación si cambia la secuencia M3U8, caducan contexto tras pausas y conservan las marcas originales además del tiempo relativo de sesión.
- Un dispositivo de audio elegido explícitamente que desaparezca no se sustituye silenciosamente por otro. Una restauración fallida de audio silenciado permanece visible y puede reintentarse.
- La elección explícita de whisper.cpp respeta CPU y Vulkan, también cuando se detecta NVIDIA. La publicación CPU no incorpora CUDA.
- La cola de eventos admite publicaciones simultáneas sin la carrera entre descarte e inserción.

### Security and distribution

- El transporte local acredita ambos extremos mediante HMAC con nonces nuevos y solicitud vinculada, sin transmitir la credencial persistente. El canal distingue cuenta/sesión de Windows y restringe acceso al usuario.
- Las conexiones locales tienen plazo absoluto, límite de ocho clientes, solicitudes de 64 KiB y respuestas de 4 MiB. Restaurar la ventana mediante una segunda instancia sigue disponible aunque el control de agentes esté desactivado.
- Los títulos externos de biblioteca y recuperación se muestran como texto plano.
- Las pruebas utilizan nombres y contextos sintéticos y una raíz de datos aislada.
- La instalación respeta las versiones bloqueadas y comprueba fallos de comandos. VERSION, fuente, metadatos instalados y metadatos empaquetados coinciden.
- Los avisos de terceros ausentes se complementan desde revisiones fijas, con SHA-256 y procedencia. El constructor falla si falta un aviso o su versión/hash no corresponde.
- El constructor permite conservar expresamente todas las versiones anteriores mediante `-PreservePreviousVersions`.

### Validation scope

- 203 pruebas automatizadas aprobadas en Windows; diez repeticiones consecutivas de las dos pruebas de clips MP4 aprobaron durante la depuración.
- Revisión independiente de las correcciones de IPC, texto remoto y fixtures: sin problemas residuales confirmados en el alcance examinado.
- No sustituye una prueba prolongada con voz real ni la comprobación en otro equipo. Las fuentes correspondientes de bibliotecas nativas siguen siendo un requisito previo a publicación.

## [1.0.1] - 2026-09-09

### Fixed

- La confirmación de un segundo candidato de voz ya no compara arreglos NumPy como valores booleanos, eliminando la caída `The truth value of an array with more than one element is ambiguous` en la diarización.
- Las hotwords modificadas durante el monitoreo se actualizan también en el transcriptor activo; una palabra eliminada deja de influir tanto en la detección como en el reconocimiento sin reiniciar la sesión.
- La segunda pasada de faster-whisper conserva VAD y se ejecuta sin hotwords, vocabulario ni contexto, de modo que puede comprobar de forma independiente el texto sugerido al modelo.
- Las secuencias de contexto o hotwords reproducidas con probabilidades anormalmente bajas se vuelven a analizar sin guía y se descartan cuando el audio no las confirma.
- Las transcripciones generadas durante silencio utilizan la probabilidad de ausencia de voz, VAD y una comprobación neutral antes de mostrarse o activar alertas.
- La interfaz deja de presentar la segunda pasada como una verificación infalible y la identifica correctamente como `segunda pasada`.
- Los fallos inesperados guardan el traceback completo en `error-details.log` dentro de la sesión local, mientras el aviso gráfico continúa mostrando un mensaje breve.

### Changed

- El análisis de hardware distingue la configuración utilizable actualmente de la configuración ideal. Si detecta una GPU NVIDIA sin CUDA preparado, recomienda directamente el instalador opcional y el modelo apropiado para su VRAM.
- En una NVIDIA con al menos 6 GB de VRAM, la recomendación ideal pasa a CUDA con `large-v3-turbo`; la alternativa CPU disponible permanece visible y seleccionable.

### Validation scope

- Las 159 pruebas automatizadas aprobaron, incluidas regresiones específicas para diarización con varios candidatos, contaminación del contexto, silencio, actualización de hotwords, verificación neutral en ambos motores y recomendación CUDA.
- La firma real de `faster-whisper` instalada acepta el control `hallucination_silence_threshold` utilizado por el parche.
- La carpeta ejecutable portable se valida de manera separada antes de sustituir la candidata pública.

## [1.0.0] - 2026-09-07

### Added

- Portada pública del repositorio con capturas reales, inicio rápido, funciones, arquitectura, privacidad, estructura, preguntas frecuentes y referencias verificadas.
- Automatización de pruebas en Windows con Python 3.12 y análisis estático de Python mediante CodeQL.
- Plantillas estructuradas para errores, propuestas y pull requests, con advertencias específicas para evitar publicar datos privados.
- Configuración mensual de Dependabot para proponer dependencias menores y correcciones de Python y GitHub Actions, sin auto-merge ni publicación automática.
- Propiedad predeterminada de Yojemr sobre el código, categorías de notas automáticas y lista de verificación para publicaciones.
- Revisión local previa al commit que enumera los archivos candidatos y detecta versiones incoherentes, archivos generados, tamaños incompatibles, credenciales comunes o rutas personales sin imprimir secretos.
- Reglas de formato y finales de línea reproducibles, más un formulario independiente para preguntas de instalación o uso.
- Guía paso a paso para crear el repositorio, revisar el primer commit, configurar las protecciones y distinguir el código fuente del portable de Windows.

### Changed

- La primera distribución pública se documenta como no firmada; su integridad se verificará mediante origen oficial y checksums SHA-256, sin convertir un certificado comercial en requisito para publicar.
- La documentación portable conserva una sola copia del README y todos sus enlaces locales permanecen utilizables fuera de GitHub.

### Fixed

- El selector de hablante de cada hotword reserva el ancho necesario para mostrar completa la opción predeterminada `Cualquier hablante`.

### Validation scope

- Las 151 pruebas automatizadas aprobaron y el ejecutable final superó tanto el autodiagnóstico CPU como la revisión visual de la interfaz.
- La suite automatizada, el portable CPU, CUDA opcional, la interfaz y el flujo audiovisual se validaron en el equipo de desarrollo.
- El flujo de clips se utilizó durante sesiones reales prolongadas con versiones candidatas del mismo núcleo.
- No estuvo disponible un segundo computador; la entrega final se valida desde una extracción nueva y aislada en el equipo disponible.
- El repositorio y el paquete permanecen sin publicar hasta la aprobación expresa de Yojemr.

## [0.9.0] - 2026-09-07

### Added

- El primer inicio crea automáticamente modelos, sesiones, transcripciones, clips, grabaciones y componentes dentro de la carpeta de datos local.
- Un asistente recomienda Tiny, Base, Small o Large-v3-turbo según el equipo, muestra tamaños y destino, y permite posponer, cancelar o reintentar.
- Whisper se descarga desde revisiones fijas de Hugging Face y cada archivo se valida por tamaño y SHA-256 antes de publicar atómicamente el modelo completo.
- El mismo asistente prepara opcionalmente los modelos de separación de hablantes ya verificados.
- El portable público se orienta a CPU. CUDA/cuBLAS queda como componente opcional separado, con confirmación de licencia, hashes fijos y sin instalar controladores.
- Se incorporan GPL-3.0-only, aviso de autoría de Yojemr, guía de contribución, primer inicio y avisos de componentes de terceros.
- El README público se reorganiza como portada completa del repositorio, con capturas reales, inicio rápido, funciones, fuentes compatibles, arquitectura, privacidad, estructura, preguntas frecuentes y referencias.
- Las capturas públicas de la interfaz principal y del asistente de primer inicio quedan versionadas en `docs/assets` para que la presentación no dependa de archivos personales ni enlaces temporales.
- La compilación recopila las licencias incluidas por las dependencias exactas y el texto/configuración de FFmpeg utilizado.
- Menú **Acerca de AuralWarden** con autoría, ausencia de garantía y acceso a la ubicación de los términos incluidos.

### Changed

- Una instalación pública nueva ya no contiene un enlace, una hotword ni la diarización de prueba preseleccionados.
- Si falta el modelo al iniciar, la interfaz abre el asistente de preparación en vez de exigir que el usuario conozca una ruta local.
- Los títulos y subtítulos procedentes de Internet se fuerzan a texto plano para que nunca se interpreten como contenido enriquecido de Qt.
- La documentación de privacidad aclara el diario incremental de recuperación y las conexiones necesarias únicamente para descargar modelos.
- El portable incluye únicamente documentación útil para ejecutar y configurar la aplicación; las validaciones históricas, borradores de arquitectura y especificaciones internas permanecen fuera del paquete público.
- La documentación del portable conserva una sola copia del README y reúne sus recursos visuales dentro de `docs/assets`.

### Optimized

- La carpeta pública base ocupa aproximadamente 528 MiB e incluye interfaz, captura, FFmpeg, transcripción CPU y diarización; los componentes NVIDIA ya no incrementan el tamaño para usuarios que no los necesitan.

### Validated

- Las descargas incompletas, alteradas, canceladas o sin espacio no reemplazan modelos existentes ni dejan una carpeta utilizable parcialmente.
- El componente CUDA opcional extrae únicamente los DLL y avisos previamente enumerados; ignora entradas ajenas del paquete y exige 1,5 GiB temporales libres.
- Una prueba de regresión confirma que títulos y subtítulos con etiquetas de imagen se muestran literalmente como texto.
- Ciento cincuenta y una pruebas automatizadas aprobaron y el ejecutable portable superó su autodiagnóstico en modo CPU.
- La edición pública CPU no contiene DLL ni paquetes NVIDIA y no presenta coincidencias de credenciales, rutas personales o enlaces de las sesiones de prueba fuera de sus dependencias de terceros.

## [0.8.4] - 2026-09-03

### Fixed

- Los interruptores de clips de audio y vídeo se sincronizan con el motor durante la sesión. Pausar y reanudar conserva los clips pendientes y permite generar nuevos clips después de reactivar la opción.
- Las opciones que preparan la captura se bloquean durante el monitoreo y explican que deben elegirse antes del inicio. Las sesiones iniciadas sin vídeo requieren un nuevo inicio para habilitarlo.
- La configuración de cada sesión se copia para evitar que cambios de la interfaz alteren parcialmente el motor en ejecución.
- FFmpeg drena sus mensajes de error en un hilo separado con un máximo de 64 KiB, evitando bloqueos de la captura cuando se llena la tubería de diagnósticos.
- La espera progresiva de reconexión limita su exponente incluso en el modo de reintentos ilimitados.
- Los directos de YouTube que publican subtítulos como segmentos WebVTT sobre una lista M3U8 ya son compatibles; el soporte JSON3 anterior se conserva.
- Si YouTube etiqueta incorrectamente el idioma de la única pista visible, AuralWarden puede utilizarla como fuente auxiliar en vez de declararla ausente. Cuando existen varias pistas, sigue priorizando de forma segura el idioma configurado.
- Los segmentos ya leídos se identifican por su secuencia y no vuelven a descargarse ni a producir entradas repetidas en cada consulta.
- La consulta de WebVTT se sincroniza con la duración real de los segmentos M3U8, evitando solicitudes más frecuentes de lo que YouTube puede actualizar.

### Optimized

- El portable para NVIDIA deja de duplicar el paquete completo de cuDNN: CTranslate2 ya incluye el cargador requerido por faster-whisper. Se conserva cuBLAS, que sí interviene en la inferencia.
- El peso funcional del portable, excluyendo los datos del usuario, baja de 2,28 GiB a 1,23 GiB (aproximadamente un 46 %) sin retirar CUDA, diarización, FFmpeg, captura de audio/vídeo ni la interfaz.
- Se conserva un listado de versiones exactas de las dependencias de construcción en `requirements-build.lock.txt`.

### Security

- La carpeta local `Archivo`, que puede contener transcripciones personales archivadas, queda excluida explícitamente de Git junto con `data` y `outputs`.
- Las descargas de modelos de diarización verifican SHA-256 y tamaño máximo antes de reemplazar archivos existentes; las huellas se contrastaron con los activos oficiales.
- Las evidencias de prueba de `design/qa`, que incluyen rutas de la máquina de desarrollo, y la caché de análisis se excluyen de Git.
- La limpieza de versiones portable conserva cualquier carpeta con datos locales o un proceso abierto y se aborta si falla la construcción.

### Diagnosed

- Verificado durante una transmisión real que YouTube exponía la pista visible del navegador como `en`, formato `vtt` y protocolo `m3u8_native`, aunque el audio y los subtítulos mostrados eran en español. La versión 0.8.3 solo aceptaba pistas españolas JSON3 y por ello la descartaba.

### Validated

- `large-v3-turbo` transcribió en la RTX 3060 con `float16` e `int8_float16`; en ambos casos se cargaron cuBLAS, cuBLASLt y el `cudnn64_9.dll` incluido por CTranslate2, sin cargar las bibliotecas del paquete cuDNN externo.
- Una copia del portable sin el cuDNN redundante superó la autocomprobación, detectó CUDA y renderizó correctamente la interfaz completa.
- El portable final 0.8.4 superó la autocomprobación y la revisión visual; su runtime ejecutó inferencia con `float16` e `int8_float16` usando exclusivamente sus bibliotecas CUDA.
- Ciento treinta y tres pruebas aprobadas, incluidas pausa/reanudación de clips MP4, interruptores de la interfaz, descargas alteradas y drenaje acotado de errores de FFmpeg.
- La versión de la interfaz, los metadatos del proyecto y `VERSION` coinciden y se comprueban antes de construir.

## [0.8.3] - 2026-09-02

### Fixed

- Los subtítulos de YouTube ya no se dan por ausentes después de una única consulta temprana: AuralWarden vuelve a buscar la pista con espera progresiva mientras el monitoreo continúa.
- Una pista encontrada se renueva periódicamente y, si su enlace temporal caduca, se obtiene uno nuevo sin reiniciar Whisper ni repetir entradas ya procesadas.
- La franja de subtítulos diferencia visualmente entre espera inicial, reintento, pista activa y ausencia prolongada con reintentos todavía activos.
- Los nombres asignados manualmente a etiquetas genéricas como `Speaker 2` dejan de reutilizarse en sesiones posteriores. Cada sesión nueva empieza con etiquetas limpias y únicamente los perfiles de voz guardados voluntariamente pueden conservar una identidad.

### Validated

- La transmisión real en la que apareció la incidencia ofrece una pista compatible después de finalizar, lo que confirma que la disponibilidad puede cambiar y debe volver a consultarse.
- Ciento diecinueve pruebas automatizadas superadas, incluidas aparición tardía de una pista, renovación después de caducar, reintento prolongado y aislamiento de nombres manuales entre sesiones.
- Flujo real del ejecutable portable comprobado entre dos procesos locales: cambio de hotword, consulta inactiva, inicio, estado activo, lectura de transcripción y detención, sin usar la configuración personal.

## [0.8.2] - 2026-08-31

### Added

- Biblioteca de transcripciones anteriores dentro de AuralWarden, con búsqueda por título, fecha o archivo y lectura legible de TXT, JSON y diarios JSONL de la versión actual o de portables anteriores conservados.
- Botón **Abrir otro archivo** para consultar transcripciones antiguas de cualquier carpeta sin moverlas ni modificarlas.
- Panel compacto y fijo en la parte superior de **Transcripción en tiempo real** que muestra las tres entradas más recientes de los subtítulos auxiliares de YouTube, su hora y el estado de la pista sin reducir la previsualización ni el monitor de recursos.
- Estados visuales para pista automática, pista proporcionada por el canal, espera y ausencia temporal de subtítulos.

### Changed

- Una voz desconocida necesita ahora tres ventanas distintas y al menos tres segundos acumulados antes de recibir una etiqueta nueva.
- La huella promedio del candidato confirmado se compara otra vez con los hablantes existentes y se conserva como centroide, en lugar de descartarse al crear la identidad.
- Los candidatos provisionales similares se depuran después de una confirmación para evitar que el solapamiento produzca etiquetas duplicadas posteriores.
- Los subtítulos visibles continúan siendo una fuente auxiliar independiente: no se mezclan con Whisper ni se exportan como transcripción principal.

### Validated

- Ciento quince pruebas automatizadas superadas, incluidas voces nuevas, ruido corto repetido, detección auxiliar, estados de pista, lectura de archivos históricos y la posición fija de los subtítulos sobre la transcripción.
- Revisión visual de la ventana principal a 1488 × 980 y de la biblioteca a 980 × 620, sin texto recortado ni superposiciones.

## [0.8.1] - 2026-08-31

### Fixed

- El resumen verde de **Preferencias > Reconocimiento > Equipo** reserva ahora espacio para varias líneas y deja de quedar recortado o cubierto por el campo **Ventana** después de pulsar **Analizar**.
- El botón **Analizar** permanece alineado en la parte superior del resumen aunque el texto ocupe varias líneas.
- El diálogo de Preferencias utiliza un tamaño mínimo compatible con el resumen completo.

### Validated

- Prueba automatizada del espacio mínimo del resumen y revisión visual con el plan real `faster-whisper / cuda / float16` de este equipo.
- Ciento siete pruebas automatizadas superadas.

## [0.8.0] - 2026-08-31

### Added

- Protocolo local, opcional y versionado para que agentes o automatizaciones manejen AuralWarden sin controlar el mouse.
- Acciones estructuradas para consultar capacidades y estado, insertar un enlace, reemplazar hotwords, iniciar, detener, restaurar la ventana y leer transcripción o alertas recientes.
- Cliente integrado en el mismo ejecutable mediante archivos JSON y ayudante `AuralWarden-Control.ps1` incluido en la carpeta portable.
- Especificación JSON Schema y guía independiente para que diferentes agentes implementen el mismo contrato.
- Credencial aleatoria propia de cada carpeta y auditoría local acotada a 500 resultados, sin argumentos ni contenido transcrito.

### Changed

- Las órdenes se procesan en el hilo de la interfaz para mantener sincronizados los controles visibles, la configuración persistida, el motor y el estado externo.
- El esquema de configuración sube a 12 e incorpora una autorización desactivada por defecto.
- Los estados externos y respuestas del protocolo eliminan usuario, contraseña, consulta y fragmento de los enlaces; la configuración privada conserva el enlace completo únicamente cuando es necesario para reutilizarlo.
- Las lecturas están limitadas a 200 elementos y las alertas externas omiten rutas de sesiones y evidencias.

### Security

- El puente reutiliza IPC local de Windows, no abre puertos de red, no acepta órdenes arbitrarias y no utiliza claves de OpenAI ni de otros proveedores.
- Los archivos y dispositivos solo pueden elegirse manualmente; la orden remota de fuente admite exclusivamente HTTP/HTTPS y demostraciones locales.
- Desactivar el control elimina la credencial y revoca clientes anteriores.

### Validated

- Pruebas de rotación y revocación de credenciales, autorización, redacción de enlaces firmados, límites, acciones permitidas y ausencia de argumentos privados en la auditoría.
- Ciento seis pruebas automatizadas superadas y flujo real entre dos procesos comprobado: cambio de hotwords, inicio, lectura de transcripción de demostración y detención.

## [0.7.0] - 2026-08-29

### Added

- Tres presets incluidos —máxima detección, equilibrado y bajo consumo— que conservan la fuente y las hotwords actuales.
- Presets personales con nombre; guardan las opciones de monitoreo pero excluyen enlaces, títulos y dispositivos locales.
- Historial local de hasta 1.000 alertas con filtros por texto y tipo de evidencia, contexto visible y apertura directa del clip o su carpeta.
- Botones compactos para abrir audio y vídeo desde cada tarjeta de actividad reciente.
- Escalas de interfaz de 90, 100, 110 y 125 %, con ocultación responsiva de información secundaria cuando falta espacio.
- Opción para activar o desactivar la adaptación dinámica desde Preferencias.

### Changed

- La adaptación ahora considera CPU, GPU, RAM y VRAM, exige carga sostenida antes de reducir trabajo y utiliza histéresis con recuperación gradual para evitar cambios repetidos.
- Los perfiles de carga continúan ajustando haz, segundas pasadas e hilos sin recargar ni cambiar el modelo durante una frase.
- Presets e historial se migran a carpetas portables futuras junto con la configuración; las sesiones y evidencias continúan sin copiarse.
- El esquema de configuración sube a 11.

### Validated

- Cien pruebas automatizadas superadas, incluidas carga sostenida, presión de memoria, privacidad de presets, persistencia del historial, filtros y apertura de evidencia.

## [0.6.0] - 2026-08-28

### Added

- Perfiles de voz voluntarios creados a partir del centroide local de un hablante detectado; se conserva únicamente una huella numérica normalizada, no la grabación usada para obtenerla.
- Reconocimiento de perfiles guardados en sesiones posteriores mediante el modelo local de embeddings de sherpa-onnx y un umbral independiente configurable.
- Columna **Hablante** en cada hotword para limitar alertas, notificaciones y clips a una voz guardada concreta.
- Administración local para actualizar o eliminar perfiles desde **Hablantes**, con migración entre carpetas portables sin mover sesiones ni evidencias.
- La actividad reciente, las notificaciones y los registros de coincidencia incluyen el hablante atribuido.
- Protección de instancia única por carpeta portable: volver a ejecutar la misma versión restaura su ventana existente.

### Fixed

- La ventana restaurada desde la bandeja comprueba periódicamente el estado real del motor y corrige cualquier indicador visual obsoleto.
- `runtime-status.json` se actualiza periódicamente mientras la aplicación está abierta, evitando que una comprobación externa confunda un estado antiguo con la sesión actual.
- La finalización del motor, la disponibilidad de **Detener**, el cronómetro, la bandeja y el estado externo vuelven a converger aunque se pierda un evento visual aislado.
- Los perfiles con una dimensión incompatible —por ejemplo, después de cambiar el modelo de embeddings— se ignoran de forma segura en vez de interrumpir la sesión.

### Validated

- Noventa y dos pruebas automatizadas superadas, incluidas persistencia y eliminación de perfiles, filtro por hablante, reconocimiento de embeddings, instancia única y reparación de estado visual.

## [0.5.1] - 2026-08-28

### Fixed

- Agregar, editar o eliminar una hotword actualiza el detector de la sesión activa después de una pausa breve de 300 ms.
- Una hotword eliminada deja de generar coincidencias, alertas y clips nuevos sin reiniciar la captura.
- La fusión temporal se reinicia al cambiar el vocabulario para no conservar detecciones pertenecientes a una configuración anterior.
- La barra de título nativa de Windows ya no añade una segunda aparición de `AuralWarden`.

### Validated

- Ochenta y tres pruebas automatizadas superadas.
- Comprobada la propagación desde el botón de eliminación hasta el motor y la ausencia posterior de coincidencias.
- Interfaz portable renderizada con la identidad `v0.5.1 · Made by Yojemr`.

## [0.5.0] - 2026-08-28

### Added

- Subtítulos manuales o automáticos de YouTube como fuente auxiliar independiente para hotwords.
- Fusión temporal entre detecciones de subtítulos y Whisper, sin duplicar alertas ni clips y sin mezclar subtítulos en la transcripción visible.
- Detección de frases compuestas aunque queden repartidas entre entradas consecutivas de subtítulos.
- Grabación completa de vídeo opcional desde la misma captura segmentada usada para los clips y guardada como MP4 en `recordings`.
- Diario incremental de transcripción y restauración guiada cuando una ejecución termina inesperadamente.
- Migración automática de preferencias compatibles desde la versión portable anterior.
- Reutilización de modelos y componentes mediante enlaces físicos del mismo disco; no se migran evidencias personales.
- Acceso directo a grabaciones completas desde el menú **Archivos**.

### Changed

- El esquema de configuración sube a 9 con controles separados para ayuda de subtítulos y vídeo completo.
- Las fuentes de audio, micrófono y radio sin vídeo deshabilitan las opciones audiovisuales incompatibles.
- Si la finalización del vídeo completo falla, los segmentos se conservan para recuperación en lugar de borrarse.
- `yt-dlp` se incorpora al perfil de captura y al paquete portable para resolver pistas públicas sin API ni credenciales.

### Validated

- Ochenta pruebas automatizadas superadas.
- Pista automática en español localizada en el enlace de YouTube usado durante el desarrollo.
- JSON3, fusión entre fragmentos, aislamiento del texto visible, diario de recuperación y migración sin datos personales comprobados.
- MP4 completo con audio y vídeo generado desde una fuente local controlada.

## [0.4.1] - 2026-08-27

### Changed

- La aplicación identifica únicamente a Yojemr como creador; la asistencia de Codex queda reconocida solo en el README.

### Fixed

- Las hotwords de varias palabras ahora se detectan aunque Whisper divida la frase entre dos o más fragmentos consecutivos de la transcripción.
- La unión interna para detección conserva intactos los fragmentos visibles y se limita a contexto temporal cercano para evitar coincidencias artificiales entre partes alejadas.
- La diarización ya no crea una identidad permanente a partir de un único turno dudoso o demasiado corto; las voces nuevas deben confirmarse entre ventanas y los centroides no se contaminan con asignaciones débiles.
- El número esperado de hablantes ahora limita las identidades de toda la sesión en lugar de forzar esa cantidad dentro de cada bloque corto.
- Se ajustó la persistencia predeterminada para tolerar mejor las variaciones de una misma voz y reducir etiquetas `Speaker` duplicadas.

### Validated

- Setenta y cuatro pruebas automatizadas superadas.
- Comprobados una frase exacta repartida entre fragmentos, una sola alerta, el clip asociado, el límite temporal del contexto y la conservación visual de los fragmentos.
- Comprobadas la confirmación de voces entre ventanas, la reutilización de turnos cortos, la resistencia a solapamientos contradictorios y el límite global de hablantes.
- Autocomprobación del portable superada con Qt, FFmpeg interno, captura de Windows, CUDA `float16`, faster-whisper y sherpa-onnx.
- Interfaz portable 0.4.1 renderizada fuera de pantalla sin errores ni recortes; paquete limpio de 2.430.607.241 bytes, sin datos de las pruebas.

## [0.4.0] - 2026-08-27

### Added

- Detección local de núcleos físicos y lógicos, RAM, adaptadores gráficos, VRAM de NVIDIA y disponibilidad efectiva de CUDA.
- Selección automática del motor, dispositivo, precisión numérica, número de hilos y modelo local más apropiado para el equipo.
- Modos **Automático**, **Precisión máxima**, **Equilibrado** y **Bajo consumo** en Preferencias.
- El modo de bajo consumo usa CPU `int8`, limita los hilos, amplía la ventana y reduce segundas pasadas y diarización para equipos modestos.
- Respaldo universal mediante `faster-whisper` en CPU cuando CUDA o sus bibliotecas locales no están disponibles.
- Nuevo adaptador opcional para `whisper.cpp`, modelos GGML/GGUF y componentes compilados con Vulkan para GPU AMD, Intel o NVIDIA.
- Campos avanzados para seleccionar el ejecutable, el modelo y declarar explícitamente si el componente `whisper.cpp` usa CPU o Vulkan.
- Administrador modular de componentes con descarga HTTPS, verificación SHA-256, extracción protegida contra rutas inseguras e instalación dentro de los datos de AuralWarden.
- Botón **Analizar** que muestra la configuración recomendada sin enviar información del equipo.
- Acción explícita **Instalar CPU** para descargar el componente oficial `whisper.cpp`, verificarlo y guardarlo en los datos locales sin mezclarlo con los archivos principales.

### Changed

- El modelo, motor, dispositivo y precisión nuevos quedan en **Automático** de forma predeterminada; la selección manual continúa disponible.
- Los modelos detectados ya no reemplazan silenciosamente la opción automática al guardar Preferencias.
- Las dependencias CUDA se separaron del núcleo STT para permitir futuras distribuciones CPU considerablemente más ligeras.
- La autocomprobación portable ya no exige una NVIDIA: valida la capacidad disponible y acepta correctamente un equipo solo CPU.
- Los consejos de configuración dejaron de estar escritos específicamente para la RTX 3060.

### Compatibility

- NVIDIA: aceleración CUDA cuando el paquete incluye cuBLAS/cuDNN y el controlador es compatible.
- Cualquier equipo: inferencia CPU local con cuantización `int8` y ajuste según núcleos/RAM.
- AMD e Intel: arquitectura y adaptador Vulkan implementados; requieren un ejecutable de `whisper.cpp` compilado con Vulkan y un modelo GGML/GGUF válidos. La versión 0.4.0 no incluye un binario Vulkan oficial de Windows, por lo que no anuncia esa aceleración automáticamente sin un componente identificado o configurado por el usuario.

### Validated

- Sesenta y cuatro pruebas automatizadas superadas, incluidas selección NVIDIA/CPU/AMD, bajo consumo, migración de configuración, lectura de JSON de `whisper.cpp` y seguridad del instalador de componentes.
- En el equipo de desarrollo se detectaron correctamente 8 núcleos físicos, 27,9 GB de RAM visibles para el proceso, RTX 3060 con 12.288 MB de VRAM, CUDA `float16` y `large-v3-turbo` como primera opción.

## [0.3.1] - 2026-08-27

### Fixed

- Los perfiles **Alerta amable**, **Aviso** y **Discreta** ahora reproducen tres archivos WAV locales realmente diferentes; ya no dependen de alias que Windows podía resolver al mismo sonido.

### Distribution

- Las bibliotecas internas se agrupan en `runtime`, la documentación en `docs` y el marcador `portable.flag` queda oculto para mantener limpia la carpeta principal.
- Se eliminan del paquete las pruebas internas de dependencias, NVRTC y NVBLAS, que no participan en la inferencia de CTranslate2 usada por AuralWarden.
- Se conservan completas cuBLAS y cuDNN para no comprometer la aceleración CUDA de `large-v3-turbo`.
- Se incorpora una autocomprobación silenciosa del portable para verificar Qt, FFmpeg, CUDA, STT, diarización y captura de Windows sin abrir la interfaz.

### Validated

- Cincuenta y seis pruebas automatizadas superadas.
- Los tres WAV fueron comprobados como archivos PCM mono válidos, distintos entre sí y presentes dentro del portable.
- La autocomprobación del ejecutable confirmó Qt, FFmpeg interno, CUDA `float16`, faster-whisper, CTranslate2, sherpa-onnx, Streamlink, PyAudioWPatch y pycaw.
- La interfaz portable se renderizó y cerró correctamente en modo fuera de pantalla, sin interrumpir otras aplicaciones.
- El paquete sin modelos pasó de 2.498,0 MB en 0.3.0 a 2.317,9 MB en 0.3.1: 180,1 MB menos, una reducción del 7,2 %.

## [0.3.0] - 2026-08-27

### Added

- Selector general de fuente con **Enlace**, **Audio del sistema** y **Micrófono**, sin perfiles temáticos ni configuraciones separadas por plataforma.
- Resolución automática de enlaces públicos de YouTube, Twitch y Kick mediante Streamlink, sin chat, cuentas ni credenciales integradas.
- Respaldo directo de FFmpeg para radio y transmisiones HLS, DASH, MP3, AAC, Ogg, Opus y listas compatibles.
- Captura WASAPI de la mezcla completa de una salida de Windows sin depender de `Mezcla estéreo` o controladores virtuales.
- Captura de micrófono con selección de dispositivo, conversión a mono 16 kHz e intentos sobre interfaces alternativas cuando WASAPI rechaza la entrada.
- Medidor de audio en el histórico de recursos para diferenciar señal, nivel bajo y silencio.
- Botón **Silenciar salida** disponible exclusivamente durante la captura del audio del sistema.
- Confirmación preventiva que explica el alcance global del silencio antes de modificar la salida.
- Acción **Restaurar audio de Windows** en la bandeja mientras la monitorización silenciosa está activa.
- Estado de recuperación local para restaurar el dispositivo al siguiente inicio después de una terminación inesperada.
- Títulos genéricos apropiados para Twitch, Kick, radio, audio del sistema y micrófono.

### Behavior

- La monitorización silenciosa conserva el volumen y estado originales y los restaura al detener, cerrar o fallar.
- La primera hotword activa inmediatamente el dispositivo, garantiza un volumen audible mínimo cuando era cero y deja la salida encendida; no vuelve a silenciarla automáticamente.
- Si el usuario activa externamente el dispositivo, AuralWarden abandona su control y respeta la decisión manual.
- Las fuentes exclusivamente de audio deshabilitan los clips MP4 y conservan clips WAV, transcripción, diarización y alertas.
- El reloj de una captura local continúa durante silencios reales mediante bloques PCM silenciosos, evitando desplazar las marcas de tiempo.

### Validated

- Cincuenta y cinco pruebas automatizadas superadas.
- Captura real de un segundo desde la salida WASAPI predeterminada, convertida a PCM mono de 16 kHz sin escribir audio en disco.
- Conversión estéreo, remuestreo, recuperación tras interrupción, restauración manual y activación permanente por hotword comprobados.
- Interfaz de audio del sistema y diálogo de confirmación revisados visualmente.
- El micrófono predeterminado de la máquina de desarrollo aparece correctamente, pero su controlador rechazó la apertura desde todas las interfaces disponibles; el error guiado y los respaldos quedaron implementados para validación posterior con otro dispositivo.

### Distribution

- Se incorporan `PyAudioWPatch`, `pycaw` y sus componentes dentro del paquete portable; no se instala ningún controlador de Windows.
- El empaquetado excluye copias externas de ICU que puedan interceptar a `QtCore` y guarda `startup-error.log` junto al ejecutable si ocurre un fallo temprano de arranque.
- Carpeta ejecutable sin ZIP y conservación máxima de las dos versiones anteriores.

## [0.2.3] - 2026-08-26

### Added

- Espera automática para directos programados que todavía no entregan audio.
- Reconexión con espera progresiva para interrupciones de Streamlink o FFmpeg, límite configurable y cancelación mediante **Detener**.
- Estados visibles **Esperando directo** y **Reconectando**, separados de una aplicación simplemente abierta.
- Archivo local `runtime-status.json` con estado, versión, proceso, fuente y sesión para comprobaciones externas fiables.
- Botones **Probar sonido** y **Probar aviso** junto a la configuración de notificaciones.
- Nombres legibles para carpetas de sesión, audio completo, transcripciones y clips WAV/MP4.

### Behavior

- Un cierre limpio después de recibir audio se interpreta como final normal del directo.
- Una fuente sin audio se interpreta como directo todavía no iniciado; un error tras recibir audio se interpreta como interrupción temporal.
- Los reintentos conservan una sola línea temporal para la transcripción y los búferes de clips.
- Los nombres repetidos reciben sufijos sencillos como `(2)` en lugar de identificadores técnicos.

### Validated

- Cuarenta y nueve pruebas automatizadas superadas.
- Espera, reconexión, continuidad temporal, límite de intentos y manifiestos de vídeo comprobados.
- Estados de interfaz, estado local consultable y pruebas de sonido/notificación comprobados.
- Convenciones legibles de nombres verificadas para sesiones, grabaciones, transcripciones y clips.

### Distribution

- Carpeta portable ejecutable sin ZIP; se conserva la versión actual y como máximo las dos anteriores.
- Limpieza automática de las carpetas intermedias de PyInstaller después de una construcción válida.

## [0.2.2] - 2026-08-26

### Added

- Agrupación de fragmentos consecutivos del mismo hablante en párrafos legibles dentro de la transcripción en vivo.
- Exportación TXT en formato de texto continuo, con una sola marca de tiempo al inicio de cada párrafo.
- Hora exacta de cada fragmento al pasar el cursor o hacer clic sobre su frase en la interfaz.
- Conteo simultáneo de fragmentos recibidos y párrafos visibles.
- Campo de hotword más alto y panel ligeramente más ancho para evitar recortes tipográficos.
- Título del directo sobre la previsualización, obtenido de información pública de YouTube sin clave privada.
- Botón **Activar vista** para iniciar y detener manualmente la previsualización sin afectar el monitoreo de audio.
- Ayudas emergentes en los campos de configuración rápida y avanzada.
- Identidad `v0.2.2 · Made by Yojemr` en el extremo inferior derecho.

### Behavior

- Un párrafo nuevo comienza al cambiar el hablante, superar ocho segundos de pausa, alcanzar noventa segundos o aproximarse a novecientos caracteres.
- La hora visible del párrafo corresponde al fragmento más antiguo, incluso si Whisper entrega dos fragmentos ligeramente desordenados.
- El JSON conserva sin agrupar todas las marcas temporales y metadatos originales.

### Validated

- Cuarenta y una pruebas automatizadas superadas.
- Agrupación, exportación, orden temporal y enlaces interactivos de tiempo comprobados.
- Activación manual de vista, identidad, tamaño de hotwords, ayudas y resolución de títulos comprobados.
- Construcción aislada de rutas de DLL externas para evitar contaminar el paquete portable.

## [0.2.1] - 2026-08-26

### Added

- Catálogo automático de modelos Whisper locales con prioridad para `large-v3-turbo`.
- Búsqueda en los datos portables, el proyecto, carpetas versionadas y la caché local de Hugging Face.
- Selector editable de modelo en Preferencias con acciones **Detectar** y **Examinar**, validación y ruta visible.
- Detección automática de los modelos locales de diarización junto al modelo Whisper.
- Menú **Archivos** con accesos directos separados a clips de vídeo, clips de audio y transcripciones.
- Carpetas de sesión independientes `clips/video`, `clips/audio` y `transcripts`.

### Validated

- Treinta y tres pruebas automatizadas superadas.
- Resolución comprobada de `data/models/large-v3-turbo` desde el proyecto y desde una carpeta ejecutable versionada.
- Apertura comprobada de los tres destinos de salida de una sesión.

### Distribution

- Las versiones de desarrollo se entregan como carpetas ejecutables sin comprimir.
- El paquete 1.0 incorporará los modelos o un instalador interno que los descargue a `data/models` y permita localizarlos automáticamente.

## [0.2.0] - 2026-08-25

### Added

- Captura simultánea de PCM y segmentos audiovisuales desde un único flujo FFmpeg.
- Búfer temporal segmentado de vídeo, limitado por tiempo y eliminado al finalizar normalmente.
- Clips MP4 con vídeo, audio y tiempos configurables antes y después de la hotword.
- Remultiplexado rápido sin recodificar y segunda estrategia de codificación cuando el medio lo requiere.
- Creación de MP4 en un hilo independiente para no pausar la transcripción ni la detección.
- Controles separados para clips WAV y MP4, además de la duración del búfer audiovisual.
- Estado de cada evidencia en la actividad reciente y conteo por alerta, sin duplicar audio y vídeo.
- Opción de consola `--video-clips`.
- Continuidad explícita al ocultar la ventana: el monitor permanece activo desde la bandeja y la previsualización se suspende para ahorrar recursos.

### Validated

- Treinta pruebas automatizadas superadas.
- Segmentación simultánea de un vídeo real de prueba mientras se extrae PCM mono a 16 kHz.
- Recorrido integrado de detección, pre-roll, post-roll y creación de MP4.
- Verificación con FFprobe de que el clip final contiene pistas de vídeo y audio.
- Eliminación del búfer temporal al cerrar normalmente la sesión.
- Cierre de la ventana con continuidad del motor en segundo plano validado.
- Migración automática de configuraciones 0.1.x al esquema de vídeo de 0.2.0.

### Known limitations

- La generación MP4 con una transmisión real de YouTube requiere todavía una validación prolongada.
- Un cierre abrupto del proceso puede dejar fragmentos temporales dentro de `.video-buffer`.
- Los subtítulos de YouTube todavía no se usan como fuente independiente.
- Las emisiones programadas que aún no han comenzado requieren reintentar manualmente.

## [0.1.2] - 2026-08-25

### Added

- Primera interfaz gráfica funcional de escritorio con PySide6.
- Cabecera de fuente y controles de inicio, detención y acceso al directo.
- Previsualización ligera mediante Streamlink y FFmpeg, con modo sincronizado o de menor latencia.
- Transcripción en vivo con marcas de tiempo, hablantes y resaltado de hotwords.
- Panel de actividad reciente y asociación del clip de audio con su alerta.
- Históricos breves de GPU, CPU, VRAM y RAM.
- Edición de hotwords, umbrales, pre-roll, post-roll, grabación, diarización y notificaciones.
- Preferencias de Whisper, segunda pasada, contexto, vocabulario y modelos de diarización.
- Asignación manual de nombres a las etiquetas de hablante.
- Bandeja de Windows con estado, última coincidencia, silenciado y detención.
- Alertas de Windows y sonidos locales configurables.
- Guardado manual de la transcripción y confirmación al cerrar si hay cambios sin exportar.
- Identidad visual de onda sin escudo y estado neutro de previsualización sin personas de relleno.
- Carga portátil de iconos sin instalar fuentes en Windows.
- Empaquetado opcional de la interfaz y FFmpeg.

### Validated

- Veinticinco pruebas automatizadas superadas.
- Recorrido gráfico de transcripción, hablante, alerta y actividad verificado en modo local.
- Captura final comparada con la referencia visual seleccionada; revisión de diseño aprobada.
- Diagnóstico local confirma FFmpeg, Streamlink, faster-whisper, sherpa-onnx y CUDA `float16`.

### Known limitations

- Los clips contienen audio WAV; el búfer y los clips MP4 todavía no están implementados.
- Los subtítulos de YouTube todavía no se usan como fuente independiente.
- Las emisiones programadas que aún no han comenzado requieren reintentar manualmente.

## [0.1.1] - 2026-08-25

### Added

- Bibliotecas oficiales cuBLAS 12 y cuDNN 9 aisladas dentro del entorno del proyecto.
- Detección automática de las DLL NVIDIA sin modificar el `PATH` global de Windows.
- Prueba reproducible de inferencia CUDA mediante `scripts/validate_model.py`.
- Perfil de alta recuperación con ventanas de 6 s y solapamiento de 2 s.
- VAD más tolerante a voces rápidas, ruido y pausas breves.
- Segunda pasada por baja confianza o audio no silencioso sin transcripción.
- Contexto y vocabulario configurables sin convertirlos en alertas.
- Palabras, probabilidades y marcas temporales individuales en cada fragmento.
- Estabilización de texto solapado y marcas de alerta basadas en la palabra exacta.
- Comando `compare-audio` para comparar dos perfiles sobre el mismo archivo.
- Diarización local con sherpa-onnx, segmentación ONNX y embeddings persistentes.
- Detección automática o número esperado de hablantes y nombres manuales.
- Descarga explícita de modelos mediante `download-diarization-models`.

### Validated

- Descarga local de `large-v3-turbo` (aproximadamente 1,62 GB).
- Inferencia real CUDA `float16` en la RTX 3060: 11 s de audio en 2,86 s.
- Recorrido completo con transcripción, hotword exacta, fusión temporal, registro y clip WAV.
- Paquete portable con Streamlink, STT y bibliotecas CUDA; inferencia real verificada desde el ejecutable.
- Monitorización real de un directo de YouTube en español durante dos minutos.
- Detección al 100 % de la hotword `ayuda` y clip de evidencia de 25 s con pre-roll y post-roll.
- Redetección de la hotword al reprocesar el clip mediante ventanas solapadas.
- Diarización del clip real en cuatro etiquetas estables y alerta ubicada en 6,47 s.
- Monitorización adicional de YouTube con 17 fragmentos, 119 palabras y tres hablantes.
- Comparación reproducible: ambos perfiles conservaron `ayuda`; el nuevo recuperó más contexto.
- Paquete portable 0.1.1 verificado con CUDA, diarización, cuatro hablantes, alerta y clip.
- Veintidós pruebas automatizadas superadas, incluida la terminación limpia de FFmpeg si el consumidor se detiene antes de tiempo.

## [0.1.0] - 2026-08-24

### Added

- Estructura portable y backend independiente de cualquier interfaz.
- Captura de archivos locales y fuentes Streamlink.
- Conversión FFmpeg a PCM mono de 16 bits y 16 kHz.
- Búfer circular de audio en RAM.
- Adaptador diferido para `faster-whisper`, CUDA y `large-v3-turbo`.
- VAD, hotwords del modelo y ventanas de transcripción solapadas.
- Detección exacta y difusa de palabras y frases.
- Segunda pasada para coincidencias dudosas.
- Fusión temporal de detecciones cercanas.
- Clips WAV con pre-roll y post-roll.
- Grabación completa de audio opcional.
- Registro JSONL de eventos y exportación opcional de transcripciones.
- Bus de eventos seguro para conectar la futura interfaz.
- Historial de recursos y perfiles adaptativos de carga.
- Comandos `doctor`, `simulate`, `capture-test`, `download-model` y `monitor`.
- Instalación aislada por perfiles y empaquetado portable del backend.
- Doce pruebas automatizadas, incluida una conversión real con FFmpeg.

### Validated

- Streamlink 8.5.0 con complemento de YouTube disponible.
- Captura remota HLS y salida PCM mono de 16 kHz.
- `faster-whisper` 1.2.1 y CTranslate2 4.8.1.
- Una RTX 3060 visible desde CTranslate2 con soporte `float16`.

### Known limitations

- La descarga del modelo es explícita para evitar transferencias y uso de disco inesperados.
- La prueba de esta versión no utiliza todavía un enlace real de YouTube del usuario.
- Los clips generados contienen audio; el vídeo se incorporará en una versión posterior.
- No hay diarización, subtítulos híbridos, notificaciones ni interfaz gráfica todavía.
