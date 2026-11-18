# Mantenimiento por versión

1. Revisa la versión de `VERSION`, las acciones y límites de `handle_local_control`, los protocolos de `local_control.py`, los subcomandos de `cli.py` y las funciones nuevas de la interfaz/backend.
2. Actualiza `capabilities.json`, `references/functions.md` y los ejemplos o ayudantes afectados. No declares que una función de interfaz está expuesta por IPC si no lo está. No copies datos de usuario, rutas de su perfil ni credenciales a la fuente distribuible.
3. Ejecuta `.venv/Scripts/python.exe scripts/check-agent-skill.py`, las pruebas de integración y el validador de skills disponible en Codex. Las pruebas estáticas no sustituyen una comprobación del comportamiento del ayudante.
4. Prueba descubrimiento sin abrir nada. Para probar órdenes usa una instancia sintética con carpeta de datos aislada, audio/notificaciones apagados y sin micrófono, loopback, vídeo de pantalla ni fuente remota. No habilites el control en una instancia real para validar la skill.
5. Si ya existe una instalación global administrada de esta skill, actualízala mediante `scripts/sync-agent-skill.ps1` desde el proyecto. Esto no habilita capturas ni cambia AuralWarden. En otros equipos, la instalación global es opcional y requiere autorización; la compilación portable nunca debe escribir en el perfil de Codex automáticamente.
6. Comprueba hashes entre la fuente y la copia global/entregada, así como el alcance del diff. La versión binaria de AuralWarden no necesita recompilarse si solo cambian instrucciones y scripts de la skill. No sobrescribas ajustes locales ajenos a la integración.

Las nuevas carpetas portables incluyen `agent-skill/`; esta copia es distribuible, no se autoactiva. Si la lista de skills de un chat abierto no se refresca, indica la ruta global de `SKILL.md` o abre un chat nuevo; no asegures que el anfitrión ya la cargó sin comprobarlo.
