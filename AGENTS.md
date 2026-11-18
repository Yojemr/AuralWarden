# AuralWarden

## Integración local para agentes

- La fuente mantenida de la skill está en `integrations/codex/auralwarden`. Consulta su `SKILL.md` al operar la aplicación o mantener su integración.
- En cada versión, revisa todas las funciones nuevas o modificadas y actualiza el catálogo, las instrucciones, referencias y ayudantes afectados. Distingue control IPC, CLI/backend e interfaz; no anuncies acciones inexistentes.
- `capabilities.json` debe coincidir con `VERSION`, los protocolos, las acciones/límites reales y los subcomandos CLI. Ejecuta `scripts/check-agent-skill.py` y las pruebas antes de compilar o entregar.
- Tras verificar una nueva versión, sincroniza la skill global del desarrollador con `scripts/sync-agent-skill.ps1` cuando esa instalación esté autorizada. En otros equipos la instalación es opcional; compilar la app no autoriza modificar perfiles de Codex.
- Prueba la integración con datos sintéticos aislados. No actives control local, capturas, sonidos, rutas de audio, descargas o recuperación de sesiones reales para probar una skill.
- No guardes credenciales ni datos personales en las skills. Conserva los datos y las sesiones existentes; no publiques, hagas commit ni borres versiones sin el alcance autorizado por el usuario.
