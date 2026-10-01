# AuralWarden 1.0.0

Primera versión pública preparada de AuralWarden, un monitor local para Windows que transcribe fuentes en vivo, detecta palabras o frases importantes y conserva evidencia únicamente cuando el usuario lo solicita.

## Funciones principales

- YouTube, Twitch, Kick, radio, enlaces directos, archivos, audio general de Windows y micrófono.
- Transcripción local mediante faster-whisper, con `whisper.cpp` como motor externo opcional.
- Hotwords exactas o difusas, incluso cuando una frase queda dividida entre fragmentos.
- Notificaciones de Windows y clips WAV o MP4 con contexto anterior y posterior.
- Grabación completa de audio o vídeo como opciones independientes y desactivadas inicialmente.
- Subtítulos auxiliares de YouTube con reintentos y soporte JSON3/WebVTT segmentado.
- Diarización, nombres manuales, perfiles de voz voluntarios y alertas condicionadas por hablante.
- Reconexión, recuperación de sesiones, bandeja del sistema y adaptación dinámica a CPU, GPU, RAM y VRAM.
- Control local opcional para agentes sin puertos, API web ni claves externas.

## Distribución

El ZIP público contiene el portable CPU completo para Windows x64. No requiere instalar Python. Los modelos se descargan desde el asistente de primer inicio y se validan antes de activarse. CUDA es un componente opcional separado para equipos NVIDIA compatibles.

El ejecutable no está firmado digitalmente, por lo que Windows puede mostrar “editor desconocido”. Descarga únicamente desde `Yojemr/AuralWarden` y compara el SHA-256 con el publicado junto al ZIP.

## Privacidad

La transcripción, las hotwords, la diarización y los perfiles de voz se procesan localmente. La red solo se utiliza para obtener fuentes remotas, consultar subtítulos o descargar modelos y componentes solicitados.

El ZIP no contiene modelos, claves, cookies, enlaces de sesiones, perfiles de voz, grabaciones, clips ni transcripciones del equipo de desarrollo.

## Validación conocida

- 151 pruebas automatizadas aprobadas.
- Auditoría local previa a publicación y análisis de seguridad preparados.
- Portable probado mediante autodiagnóstico y desde una extracción nueva en el equipo de desarrollo.
- Sesiones prolongadas del flujo de clips comprobadas durante versiones candidatas.
- No estuvo disponible un segundo computador para una validación independiente de la versión 1.0.0.

Consulta `README.md`, `CHANGELOG.md`, `SECURITY.md` y `docs/THIRD_PARTY_NOTICES.md` para información completa.

