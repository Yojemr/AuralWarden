# AuralWarden 1.1.0

## Audio de aplicación

- Nueva fuente **Audio de aplicación**, con selección manual de una ventana para identificar el proceso y sus descendientes.
- Captura WASAPI nativa sin extensiones, controladores nuevos ni cambios de volumen.
- Mantiene transcripción local, VAD, diarización, hotwords entre fragmentos, alertas, clips WAV y audio completo opcional.
- Vídeo completo o clips MP4 opcionales de la ventana elegida, con el audio de la aplicación en lugar de toda la mezcla de Windows.
- Captura de audio independiente de la visibilidad de la ventana; el vídeo continúa requiriendo una ventana no minimizada.
- Verificación de PID, fecha de creación y ejecutable. No se sustituye una aplicación cerrada ni se pasa al audio general ante errores.
- Activación y lectura nativas en un proceso auxiliar cancelable, memoria acotada y remuestreo continuo a 16 kHz mono.

## Compatibilidad y límites

La captura real breve de Chrome/Meet funcionó en el Windows 10 del equipo de desarrollo. La disponibilidad de la API se comprueba al iniciar, sin garantizar todas las compilaciones de Windows. En Chrome puede abarcar otras pestañas y ventanas que pertenezcan al mismo árbol de procesos; no es aislamiento por pestaña.

El silencio selectivo manteniendo la captura **no está incluido**. La prueba con dos fuentes sintéticas confirmó el aislamiento, pero al silenciar la sesión de audio elegida también desapareció su señal capturada. No debe silenciarse la aplicación en el mezclador esperando que siga transcribiéndose. Una salida física o virtual separada queda como siguiente paso, sin instalarla ni reconfigurarla automáticamente.

## Fiabilidad y distribución

- Pruebas de identidad de proceso, remuestreo, silencio, límites, cancelación, selección de interfaz y continuidad del motor de hotwords.
- El entorno de pruebas de GitHub se prepara en un entorno virtual separado para no mezclar dependencias con las herramientas del servidor.
- La prueba que finaliza un MP4 requiere FFmpeg explícitamente, como las demás pruebas audiovisuales.
- Portable local en carpeta, sin ZIP, modelos, CUDA, datos personales, grabaciones ni selección previa de aplicaciones.
