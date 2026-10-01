# Lista de verificación para publicaciones

Esta lista se completa antes de crear una versión pública de AuralWarden. Las primeras compilaciones se distribuirán sin firma digital y se identificarán mediante su origen oficial y checksum SHA-256.

## Código y versión

- [ ] `scripts\check-publication.ps1 -RunTests` finalizó correctamente.
- [ ] El árbol de trabajo contiene únicamente cambios destinados a la publicación.
- [ ] `VERSION`, `pyproject.toml`, `auralwarden.__version__` y la interfaz muestran la misma versión.
- [ ] `CHANGELOG.md` describe los cambios y no contiene información privada.
- [ ] La documentación, capturas y enlaces corresponden a la versión publicada.
- [ ] Las licencias y avisos de terceros están actualizados.
- [ ] Se incluyen fuentes correspondientes, avisos y recetas aplicables a las bibliotecas nativas exactas redistribuidas; no basta con el inventario de ruedas Python.

## Calidad y seguridad

- [ ] La suite local completa aprueba en Windows.
- [ ] GitHub Actions aprueba en la rama o etiqueta que se publicará.
- [ ] CodeQL no presenta hallazgos pendientes de severidad alta o crítica.
- [ ] Se revisaron cambios sensibles en descargas, archivos comprimidos, subprocesos, IPC, rutas y texto remoto.
- [ ] No se incluyen credenciales, cookies, modelos, perfiles de voz, sesiones, enlaces privados, grabaciones ni transcripciones.

## Portable público CPU

- [ ] Se construyó desde un entorno limpio usando las dependencias bloqueadas.
- [ ] El autodiagnóstico reconoce interfaz, FFmpeg, captura, CPU `int8` y dispositivos compatibles.
- [ ] El primer inicio crea sus carpetas sin depender de rutas de la máquina de desarrollo.
- [ ] Se completó una descarga real de modelo y la verificación de integridad.
- [ ] Se comprobó una sesión con detección, notificación, transcripción y clip.
- [ ] La carpeta funciona después de copiarla a otra ubicación de Windows.

## CUDA opcional

- [ ] La edición pública sigue funcionando sin componentes NVIDIA.
- [ ] La descarga requiere aceptación explícita de los términos correspondientes.
- [ ] Los archivos se validan antes de publicarse dentro de `data/runtime/components`.
- [ ] Se comprobó inferencia real en una GPU NVIDIA compatible.

## Entrega

- [ ] Se generó el ZIP únicamente para la versión pública aprobada.
- [ ] El ZIP contiene la carpeta portable completa y no contiene `data` personal.
- [ ] Se calculó y publicó el SHA-256 del archivo entregado.
- [ ] El ZIP se probó después de extraerlo en una carpeta nueva.
- [ ] Las notas indican que el ejecutable no está firmado y explican cómo verificar el SHA-256.
- [ ] Las notas de la publicación indican requisitos, limitaciones conocidas y procedimiento de actualización.
