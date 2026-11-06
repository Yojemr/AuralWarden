# AuralWarden 1.3.0 — Revisión de sesiones

## Revisión de sesiones

- **Transcripciones > Buscar palabras:** búsqueda dentro del texto abierto con Ctrl+F, contador y botones Anterior/Siguiente. La búsqueda por título, fecha o nombre de archivo sigue disponible por separado.
- **Menú > Momentos > Marcar momento:** añade una nota en el instante del audio capturado. Ctrl+M funciona cuando la aplicación tiene el foco. Escribir después la nota no desplaza ese instante.
- **Marcadores** en una transcripción anterior permite consultar, añadir con HH:MM:SS o eliminar notas. No modifica el TXT, JSON o JSONL original.
- **Crear clip manual:** desde Momentos, la bandeja o Ctrl+Alt+C. Usa los segundos anteriores/posteriores y los tipos de clip activados; espera a completar el intervalo posterior. El vídeo debe estar preparado antes de iniciar y no se activa por sorpresa.

Los clips manuales no se presentan como hotwords ni generan su sonido o restauración de audio. Las hotwords automáticas siguen funcionando independientemente. Si solo se necesita una nota, usa un marcador: no solicita audio ni vídeo adicional.

## Límites y privacidad

Los marcadores se almacenan únicamente en `data/bookmarks.json`, con una referencia a la sesión o archivo original. Mover esa sesión o exportarla fuera de su carpeta no reasocia automáticamente las notas a la nueva ruta. El límite es de 1.000 marcadores y 1.000 caracteres por nota; no se eliminan notas anteriores automáticamente.

El reloj usa el audio recibido, no la posición retrasada de Whisper. Puede tener la resolución de un bloque de captura. Si la sesión termina antes del intervalo posterior de un clip, este puede quedar marcado como incompleto; si la captura falla antes de procesar la solicitud, se comunica la cancelación. Se permiten como máximo ocho clips manuales en curso. La búsqueda muestra hasta 10.000 coincidencias por consulta.

## Distribución

La suite local aprobó 285 pruebas. La validación incluye cambios rápidos de búsqueda con Enter, carpetas `Transcripts` con distintas mayúsculas y rechazo de tiempos inválidos en marcadores, conservando intactos los archivos existentes ante errores. También se comprobaron clips manuales con audio sintético y la continuidad de las hotwords, sin capturar contenido de otras aplicaciones ni cambiar sus salidas de audio.

Esta Release contiene únicamente código fuente, sin instalador ni ejecutables adjuntos. La publicación de binarios queda pendiente de completar la preparación de fuentes correspondientes de sus bibliotecas nativas. Para ejecutar esta versión consulta las instrucciones desde código fuente del README.

Esta actualización no instala componentes nuevos ni modifica las salidas de audio de otras aplicaciones por sí sola. Las pruebas automatizadas y sintéticas no sustituyen una prueba prolongada de esta versión en otros equipos.
