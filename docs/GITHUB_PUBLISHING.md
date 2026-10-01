# Publicación inicial en GitHub

Este procedimiento se utiliza cuando AuralWarden haya superado la lista de verificación de la versión pública aprobada.

## Crear el repositorio

1. Crea `Yojemr/AuralWarden` como repositorio público.
2. No añadas desde GitHub un README, una licencia ni un `.gitignore`; esos archivos ya existen localmente.
3. Mantén `main` como rama predeterminada.

## Revisar y crear el primer commit

Desde la raíz de AuralWarden:

```powershell
.\scripts\check-publication.ps1 -RunTests
git status --short
git add .
git status --short
git commit -m "Publicación inicial de AuralWarden"
git remote add origin https://github.com/Yojemr/AuralWarden.git
git push -u origin main
```

Si `origin` ya existe, comprueba su dirección con `git remote -v` en vez de añadirlo otra vez. Nunca uses `git add -f` para incorporar `data`, `outputs`, `Archivo`, modelos, clips o transcripciones.

## Configuración recomendada del repositorio

- Descripción: `Monitor local para Windows con transcripción en vivo, alertas por hotwords y clips automáticos.`
- Temas: `speech-to-text`, `whisper`, `local-ai`, `livestream`, `hotword`, `transcription`, `windows`, `pyside6`.
- Habilita **Issues** y el reporte privado de vulnerabilidades.
- Mantén los permisos predeterminados de GitHub Actions en solo lectura.
- Activa las alertas de Dependabot y las actualizaciones de seguridad.
- Dependabot solo propondrá actualizaciones menores o correcciones una vez al mes; no existe auto-merge ni un calendario automático de versiones.
- Protege `main` después de la primera ejecución correcta y exige las comprobaciones de pruebas y CodeQL antes de fusionar cambios.

## Primera entrega

1. Completa `docs/RELEASE_CHECKLIST.md`.
2. Construye el portable CPU desde las dependencias bloqueadas.
3. Extrae y prueba una copia nueva del ZIP final.
4. Calcula su SHA-256 con `Get-FileHash`.
5. Crea una publicación con la etiqueta de versión correspondiente y adjunta manualmente el ZIP y su checksum.
6. Indica claramente que el ejecutable no está firmado digitalmente.

Los archivos automáticos **Source code (zip)** y **Source code (tar.gz)** de GitHub contienen únicamente el código fuente; no sustituyen el portable de Windows.
