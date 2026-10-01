# Especificación visual 0.2.0

## Ventana principal

- Barra superior con enlace, iniciar, detener y abrir transmisión.
- Columna izquierda con previsualización, estado, relojes y recursos.
- Área central dominante con transcripción, marcas de tiempo, hablantes y hotwords resaltadas.
- Columna derecha con actividad reciente y estado del clip correspondiente.
- Configuración inferior dividida en hotwords, clips, grabación, notificaciones y hablantes.
- Pie con guardado de transcripción, último evento y cantidad de clips.

La referencia de estructura es `design/references/auralwarden-ui-selected.png`. La identidad visual posterior de onda sustituye el escudo inicial. Las fotografías del mockup no forman parte de la aplicación.

## Previsualización

- `Live`: menor latencia disponible.
- `Synced`: retraso controlado para coincidir con el texto confirmado.

En espera se muestra una marca neutral. Durante una fuente real se solicitan fotogramas de baja frecuencia para limitar consumo.

## Cierre

Si existe una transcripción sin exportar, se ofrecen las acciones guardar, descartar o cancelar. Los clips WAV, los clips MP4 y el audio completo se administran de forma independiente.

## Bandeja de Windows

- Estado de la sesión.
- Tiempo de funcionamiento.
- Última coincidencia.
- Acciones abrir, silenciar y detener.
- La vigilancia continúa con la ventana oculta; salir termina el proceso.

## Accesibilidad y legibilidad

- Interfaz oscura con contraste alto y acentos limitados.
- Iconos de Font Awesome acompañados de etiquetas de texto en las acciones principales.
- Hablantes diferenciados por etiqueta y color, sin depender de retratos.
- Tamaño mínimo base de 1080 × 700, escala seleccionable entre 90 y 125 % y ocultación responsiva de información secundaria.
