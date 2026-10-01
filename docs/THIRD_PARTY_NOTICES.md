# Componentes de terceros

La GPLv3 de AuralWarden se aplica a su código original. No cambia las licencias de modelos, bibliotecas, iconos o herramientas externas. Los nombres de proyectos indican procedencia, no patrocinio ni respaldo de sus autores.

| Componente | Función | Licencia / fuente primaria |
| --- | --- | --- |
| [Whisper](https://github.com/openai/whisper) | Modelos de reconocimiento | MIT |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Reconocimiento local | MIT |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | Motor de inferencia | MIT; sus bibliotecas nativas tienen avisos adicionales |
| [Streamlink](https://github.com/streamlink/streamlink) | Resolución de fuentes | BSD-2-Clause |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Metadatos y subtítulos | Unlicense para el código del proyecto; revisar componentes incorporados |
| [FFmpeg](https://ffmpeg.org/legal.html) | Captura, audio y vídeo | Depende de la compilación. La utilizada localmente tiene `--enable-gpl --enable-version3` |
| [PyAV](https://github.com/PyAV-Org/PyAV) | Lectura de audio para Whisper | BSD-3-Clause; las bibliotecas FFmpeg incluidas tienen sus propias condiciones |
| [Qt / PySide6](https://doc.qt.io/qtforpython-6/licenses.html) | Interfaz | LGPLv3 / GPLv3 según componente; no se presume una licencia comercial |
| [QtAwesome](https://github.com/spyder-ide/qtawesome) | Iconos de interfaz | MIT para el código; fuentes e iconos conservan sus avisos |
| [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz) | Coincidencia aproximada | MIT |
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Separación y comparación de voces | Apache-2.0 para su código |
| [pyannote segmentation-3.0](https://huggingface.co/pyannote/segmentation-3.0) | Segmentación de voz, conversión ONNX distribuida por sherpa-onnx | MIT; se conserva la licencia incluida en el paquete |
| [3D-Speaker](https://github.com/modelscope/3D-Speaker) | Huellas de voz ERes2Net | Apache-2.0 para el proyecto; consultar el modelo concreto distribuido por sherpa-onnx |
| [whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Motor alternativo opcional | MIT |
| [NVIDIA CUDA](https://docs.nvidia.com/cuda/eula/index.html) | Aceleración opcional | Licencia propietaria NVIDIA, no GPL ni MIT |
| [NVIDIA cuDNN](https://docs.nvidia.com/deeplearning/cudnn/latest/reference/eula.html) | Cargador de inferencia opcional | Licencia propietaria NVIDIA; se descarga únicamente al preparar CUDA |

El catálogo de instalación conserva la revisión exacta y SHA-256 de cada archivo. Los modelos Tiny/Base/Small proceden de los repositorios `Systran/faster-whisper-*`; Turbo procede de `dropbox-dash/faster-whisper-large-v3-turbo`, antes publicado bajo `mobiuslabsgmbh`.

## Redistribución

Los avisos completos disponibles en los paquetes instalados se recopilan en `docs/licenses`, junto con un inventario de versiones, al preparar el portable. Ese inventario no sustituye las obligaciones de cada licencia.

Los paquetes que no incluyen avisos suficientes en la rueda se complementan mediante `vendor-notices.json` y `vendor-notices/`, conservados desde revisiones exactas de sus repositorios originales. El constructor valida versión y SHA-256, incluye también archivos llamados `LICENCE` y rechaza dependencias sin avisos. Los textos de Qt de código abierto complementan los avisos comerciales presentes en sus metadatos; no se adquiere ni se presume una licencia comercial.

Al publicar binarios deben ofrecerse las fuentes correspondientes requeridas por GPL/LGPL, conservar avisos y comprobar las condiciones de cada biblioteca nativa redistribuida. Una URL genérica a la versión más reciente no equivale a las fuentes de la compilación distribuida. Las bibliotecas NVIDIA no quedan relicenciadas por incluirlas en una carpeta junto a AuralWarden.

La colección de avisos 1.0.2 no cierra todavía la correspondencia entre fuentes, recetas de compilación y bibliotecas nativas incluidas por FFmpeg, PyAV, Qt y los motores de inferencia. Este punto permanece pendiente de la preparación pública; el inventario no debe presentarse como aprobación legal de la distribución.

## Uso responsable

La transcripción, las atribuciones de voz y las coincidencias son estimaciones y pueden fallar. AuralWarden no garantiza que cada mención produzca un aviso ni que una etiqueta de hablante sea correcta. El software se proporciona sin garantía en los términos de su licencia; este aviso no elimina derechos ni responsabilidades que imponga la legislación aplicable.

Los usuarios deben contar con los permisos necesarios para captar, conservar o compartir audio, vídeo y voces, y respetar las condiciones de las plataformas. Las licencias de software no conceden derechos sobre el contenido monitorizado.
