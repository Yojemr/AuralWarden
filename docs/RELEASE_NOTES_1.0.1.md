# AuralWarden 1.0.1

Versión candidata para la primera publicación de AuralWarden, centrada en corregir incidencias encontradas durante sesiones reales de monitoreo antes de crear el repositorio público.

## Correcciones principales

- Evita la caída de la diarización al confirmar varios candidatos de voz.
- Actualiza inmediatamente las hotwords del detector y del transcriptor durante una sesión.
- Comprueba sin texto sugerido las transcripciones que podrían estar repitiendo el contexto, el vocabulario o las hotwords configuradas.
- Reduce alucinaciones durante silencios mediante VAD, probabilidad de ausencia de voz y una segunda pasada independiente.
- Cambia la etiqueta `verificado` por `segunda pasada` para no prometer una certeza que el modelo no puede garantizar.
- Conserva un diagnóstico técnico local junto a las sesiones que fallen, sin mostrar datos internos en el aviso gráfico.
- Recomienda preparar CUDA cuando se detecta una NVIDIA compatible aunque el componente aún no esté instalado, y distingue esa configuración ideal de la alternativa CPU disponible.

## Privacidad

El procesamiento continúa siendo local. Los archivos de diagnóstico se guardan únicamente dentro de la carpeta de la sesión y no forman parte del código ni del paquete público. AuralWarden no requiere claves de API.

## Validación conocida

- 159 pruebas automatizadas aprobadas.
- Regresiones cubiertas para el error NumPy de diarización, contaminación por texto sugerido, falsos fragmentos durante silencio, hotwords eliminadas en vivo y recomendación CUDA.
- Compatibilidad del nuevo parámetro de faster-whisper confirmada con la versión fijada en el entorno de compilación.
- No estuvo disponible un segundo computador para una validación independiente.

Consulta `README.md`, `CHANGELOG.md`, `SECURITY.md` y `docs/THIRD_PARTY_NOTICES.md` para información completa.
