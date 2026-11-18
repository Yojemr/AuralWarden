# AuralWarden 1.5.0 — Revisión audiovisual

## Uso

1. Abre **Transcripciones** y selecciona una transcripción guardada.
2. Pulsa una frase o **Vídeo / audio**. El reproductor solo se crea cuando se abre una grabación, no al iniciar el monitoreo.
3. Si existe una única grabación completa reconocida en la carpeta `recordings` de una sesión terminada, se asocia automáticamente. También puedes usar **Elegir vídeo / audio**.
4. Pulsa una frase para mostrar su instante en pausa, introduce **HH:MM:SS.mmm** o usa el deslizador. **Reproducir** inicia la reproducción continua. **Silencio** afecta únicamente al reproductor, no al audio de Windows ni a otras aplicaciones.
5. Usa **Marcar inicio**, **Marcar fin** o escribe sus tiempos de sesión. **Exportar intervalo como clip** solicita una ubicación nueva y genera MP4 para vídeo o WAV para audio. La grabación y la transcripción originales no se modifican.

## Tiempo y precisión

JSON y JSONL conservan el tiempo de cada fragmento. En TXT se utiliza la marca del párrafo; no se inventan tiempos individuales para sus palabras. El resaltado sigue la reproducción sin desplazar automáticamente el texto ni alterar la selección de búsqueda.

Las nuevas grabaciones completas de vídeo guardan un archivo `<grabación>.timeline.json`, con el mapa entre el reloj de sesión y el archivo concatenado. Los índices se vinculan al tamaño y fecha de modificación del archivo: si este cambia, no se da por válida su sincronización. No se sigue ninguna ruta de vídeo escrita en metadatos antiguos hacia otro lugar o hacia Internet.

Una transcripción o grabación antigua puede no disponer de índice. En ese caso se supone inicialmente un comienzo en cero y se muestra la advertencia; el desfase manual permite ajustar la comparación. **Tiempo de sesión = tiempo del archivo o de su índice + desfase**. Este ajuste no reconstruye cortes desconocidos de grabaciones antiguas.

Si un intervalo contiene una interrupción sin vídeo registrado, la exportación se rechaza: no se presenta como un clip continuo con evidencia inexistente. El salto sigue las marcas de la transcripción y los fotogramas disponibles; no corrige errores previos de Whisper ni garantiza precisión superior a la del archivo y sus marcas.

## Recursos y conservación

El reproductor permanece oculto inicialmente, no reproduce audio automáticamente y descarga el archivo al cerrar la biblioteca. La reproducción y exportación son independientes del motor de reconocimiento. No se permite sustituir un archivo existente; durante una exportación se bloquea el cambio de transcripción o fuente. Cerrar la biblioteca solicita cancelar la exportación y espera su finalización sin destruir el trabajador activo.

La exportación usa el FFmpeg existente y limita la codificación a dos hilos. La lectura de duración reutiliza PyAV. Los archivos temporales de exportación se crean junto al destino y se retiran al finalizar o cancelar; las referencias de red anidadas no se habilitan para el reproductor ni para la exportación.

## Alcance de esta entrega

La revisión corresponde a archivos ya guardados; no busca dentro de una grabación completa que todavía se esté finalizando. No se añade una grabación continua obligatoria ni se altera la detección de hotwords. Sin una grabación disponible, la transcripción y sus búsquedas siguen siendo utilizables.

Entrega portable local, sin publicación automática ni reconstrucción del instalador 1.4.1. Se conserva la receta reutilizable del instalador. La validación prolongada con grabaciones reales y la distribución binaria pública mantienen sus comprobaciones pendientes.

## Referencia técnica

- [Configuración del motor multimedia de Qt](https://doc.qt.io/qtforpython-6.11/overviews/qtmultimedia-advanced-ffmpeg-configuration.html).
