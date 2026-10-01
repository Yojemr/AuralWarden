# Primer inicio y actualización

## Paquete portable

1. Extrae la carpeta completa en una ubicación de Windows donde puedas escribir. No ejecutes el programa dentro de un ZIP ni copies únicamente el `.exe`.
2. Abre `AuralWarden.exe`. No necesita Python instalado cuando se usa el paquete completo.
3. Si no hay modelos disponibles, aparece **Preparar AuralWarden**. Analiza el equipo y recomienda un modelo; no descarga hasta pulsar **Preparar**.
4. Puedes elegir Tiny, Base, Small o Large-v3-turbo. Los tamaños aproximados son 75, 141, 464 y 1.547 MiB, respectivamente. Son modelos multilingües; un modelo ligero puede perder más palabras.
5. La separación de hablantes es opcional y requiere otros modelos. Activa su preparación si la necesitas.
6. Pulsa **Usar este modelo**, indica la fuente y añade tus hotwords. El monitoreo comienza solo cuando pulses **Iniciar**.

El asistente también está en **Preferencias → Reconocimiento → Modelos · Descargar / preparar**. Si pospones la instalación, puedes recorrer la interfaz; el monitoreo real requiere un modelo compatible.

## Archivos y privacidad

La aplicación crea `data/models`, `data/sessions`, `data/transcripts`, `data/clips/audio`, `data/clips/video`, `data/recordings` y `data/runtime/components`. La evidencia de cada sesión se organiza bajo `data/sessions`; los botones de carpetas abren las ubicaciones correspondientes. La variable avanzada `AURALWARDEN_DATA_DIR` puede cambiar la raíz.

Los modelos nuevos se descargan dentro de `data/models`. Las revisiones y los SHA-256 se fijan en el catálogo incluido. Cada descarga se prepara en una carpeta temporal y solo se activa al completar todas sus verificaciones. Cancelar o reintentar no sobrescribe modelos existentes. Una interrupción de Windows puede dejar una carpeta bajo `data/models/.downloads`; nunca se considera un modelo instalado.

Los modelos ya encontrados en otra instalación o caché se reutilizan sin copiarlos. Esas carpetas deben permanecer disponibles. Si quieres llevar la aplicación a otro PC, copia también los modelos que use o prepara allí una instalación nueva.

Las descargas contactan Hugging Face y, para hablantes, GitHub. No necesitan cuentas, tokens ni cookies del navegador. Esos proveedores reciben la IP de conexión; el audio y la transcripción no se envían al descargar modelos.

## Actualizar

Conserva la carpeta anterior hasta verificar la nueva. Detén el monitoreo y guarda las transcripciones antes de cambiar de versión. La migración puede reutilizar preferencias y modelos de versiones portables cercanas; no borra la instalación anterior. Las clases archivadas y otras transcripciones no deben incluirse en una publicación.

## Problemas frecuentes

- **Sin Internet:** puedes usar un modelo local existente. Si la descarga falla, pulsa **Preparar / Reintentar**; no se reanuda un archivo parcial, se vuelve a descargar.
- **Sin espacio:** libera espacio o ubica la carpeta portable en otra unidad antes de descargar. Se exige un margen adicional de 100 MiB para Whisper.
- **Carpeta de modelo ya existente pero distinta:** no se reemplaza. Usa **Examinar** para seleccionar un modelo válido o elige otro del catálogo.
- **Sin CUDA:** se usa CPU con precisión `int8`. Tener una GPU AMD/Intel no implica que Vulkan esté instalado; el adaptador sigue siendo opcional.
- **No hay subtítulos de YouTube:** la transcripción local continúa; la disponibilidad depende de la pista que exponga la plataforma.
- **Cancelar tarda:** la ventana permanece disponible mientras la operación de red termina o agota su espera. No fuerces el cierre si hay una descarga activa.
