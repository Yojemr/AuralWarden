# Contribuir a AuralWarden

## Entorno local

Usa Windows de 64 bits y Python 3.12. Desde una copia del código:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,desktop-cpu]" -c requirements-build.lock.txt
.\.venv\Scripts\python.exe -m pytest
```

FFmpeg debe estar disponible para las pruebas audiovisuales. El entorno queda aislado en `.venv`; los modelos no forman parte del repositorio.

## Cambios

- Describe el problema, comportamiento esperado y alcance del cambio.
- Añade una prueba de regresión para cada corrección. Mantén la transcripción, las alertas, el búfer y la interfaz desacoplados.
- Conserva el procesamiento local, el control de agentes desactivado por defecto y la captura solo por orden del usuario.
- Mantén sincronizadas `VERSION`, `pyproject.toml`, `auralwarden.__version__` y `CHANGELOG.md`.
- No añadas credenciales, cookies, perfiles de voz reales, enlaces firmados, transcripciones personales ni modelos. Usa ejemplos sintéticos.
- No copies código de terceros sin conservar su licencia y atribución.

Las contribuciones al código original se reciben bajo GPL-3.0-only. No se exige transferencia de derechos de autor. Describe cualquier material de terceros añadido y su procedencia.

## Informar errores

Incluye versión de AuralWarden y Windows, modo CPU/CUDA, modelo, pasos reproducibles y resultado esperado. Comparte únicamente un ejemplo público o sintético. Revisa las capturas y registros antes de adjuntarlos; las carpetas `data` y `Archivo` son privadas.

Para vulnerabilidades, sigue `SECURITY.md` y evita publicar detalles sensibles en un issue abierto.
