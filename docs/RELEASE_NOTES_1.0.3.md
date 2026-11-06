# AuralWarden 1.0.3

## Vídeo de ventanas locales

La interfaz original incorpora la fuente **Ventana + audio del PC**. Permite elegir una ventana, como una reunión de Google Meet en Chrome, y utilizar la transcripción, las hotwords, los clips y la grabación completa opcional sobre esa captura.

- Vídeo H.264 de hasta 720p, a 15 fps, y audio AAC.
- Audio loopback de la salida seleccionada, sin silenciar Windows.
- Selección de ventana explícita en cada apertura.
- Proceso de captura nativo aislado y memoria acotada.
- Sin cambio automático al escritorio ni a otra ventana.
- Unión de segmentos con duraciones explícitas para evitar acumulación de desfases en grabaciones largas.
- Grabación inmediata sin Whisper mediante `AuralWarden.exe --record-window <HWND>` y botón **Detener y guardar vídeo**.

## Alcance

Se graba el contenido visible de la ventana seleccionada: cambiar de pestaña en ella cambia también lo grabado. El audio corresponde a toda la mezcla de la salida de Windows, no exclusivamente al navegador. Mantén la ventana sin minimizar. Los segmentos se conservan si falla la captura o el guardado.

El reconocimiento, la diarización y las alertas conservan las limitaciones documentadas en las versiones anteriores. Esta entrega local no publica el código ni los binarios y no incluye modelos personales o grabaciones.
