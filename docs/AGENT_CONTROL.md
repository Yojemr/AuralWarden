# Control local para agentes

AuralWarden ofrece un protocolo local y opcional para que una IA, un script u otra herramienta pueda manejar las funciones habituales sin controlar el mouse. No es una API web: no abre puertos, no escucha en la red y no requiere claves de OpenAI ni de otro proveedor.

## Activación

1. Abre **Preferencias > Comportamiento**.
2. Marca **Permitir órdenes locales de agentes y automatizaciones**.
3. Lee la advertencia y confirma.

Al habilitarlo, AuralWarden crea una credencial aleatoria exclusiva de esa carpeta portable. El ejecutable la agrega internamente a cada solicitud; no debe copiarse a un prompt, documento ni repositorio. Desactivar la opción elimina la credencial y revoca el acceso anterior.

Desde 1.0.2 el transporte interno utiliza un intercambio autenticado de versión 2: primero acredita al servidor y después firma la solicitud. La credencial persistente no se transmite por el canal. El formato público de órdenes continúa siendo versión 1 y el ayudante se utiliza de la misma manera.

## Enviar una solicitud

La aplicación debe estar abierta, aunque puede permanecer minimizada. Guarda una orden como JSON; por ejemplo:

```json
{"action": "status"}
```

Después ejecuta el ayudante que está junto a la aplicación:

```powershell
.\AuralWarden-Control.ps1 `
  -Request .\solicitud.json `
  -Output .\respuesta.json
```

Un agente también puede llamar directamente a `AuralWarden.exe --control-request solicitud.json --control-output respuesta.json` y esperar a que el proceso termine. La respuesta siempre es JSON e incluye `ok`, `code`, `message`, `protocol_version` y `request_id`.

## Acciones

| Acción | Campos adicionales | Resultado |
|---|---|---|
| `capabilities` | Ninguno | Acciones y límites disponibles. |
| `status` | Ninguno | Estado, fuente sin parámetros privados, tiempo, hotwords, contadores, señal de audio y fase de enrutamiento. |
| `set_source` | `source` | Inserta un enlace HTTP/HTTPS para la siguiente sesión. |
| `set_hotwords` | `hotwords` | Sustituye la lista y actualiza también una sesión activa. |
| `start` | Ninguno | Inicia el monitoreo con la configuración visible. |
| `stop` | Ninguno | Detiene la sesión activa. |
| `transcript` | `limit`, máximo 200 | Devuelve los fragmentos recientes con hablante y tiempo. |
| `alerts` | `limit`, máximo 200 | Devuelve alertas recientes sin rutas de archivos. |
| `show` | Ninguno | Restaura la ventana. |
| `list_windows` | `application` | Consulta ventanas visibles del ejecutable indicado y devuelve identificadores válidos durante dos minutos o hasta la siguiente consulta. |
| `list_audio_devices` | `kind` | Dispositivos de `system_audio` o `microphone`. |
| `select_windows_source` | `kind`, `window_id` y/o `device` | Selecciona una fuente para el próximo inicio. `application_audio` exige ID. `window_capture` exige ID y dispositivo de salida. `system_audio` y `microphone` exigen su dispositivo. |
| `configure_session` | `options` | Actualiza con el monitoreo detenido `diarization`, `save_full_audio`, `save_full_video`, `audio_clips`, `video_clips`, `clip_pre_seconds` y `clip_post_seconds`. |
| `set_stop_timer` | `duration_seconds` o `stop_at_epoch` | Programa la detención. Una orden sin campos cancela el temporizador. |
| `create_clip` | Ninguno | Solicita un clip en una sesión que ya recibe audio y tiene clips habilitados. Devuelve el identificador del evento. |
| `save_transcript` | Ninguno | Guarda el texto disponible con nombre nuevo en la carpeta de transcripciones y devuelve el nombre del archivo. |
| `separate_audio` | `application`, `confirmed: true` | Solicita enviar la aplicación monitoreada al VB-CABLE disponible. |
| `restore_audio` | Ninguno | Solicita recuperar la salida original de la aplicación separada. |

Para separar Chrome, consulta `list_windows` con `application: "chrome"`, elige el identificador que corresponda y usa `select_windows_source` con `kind: "application_audio"`. Tras `start`, espera a que llegue audio. Con autorización para la aplicación completa, envía `separate_audio` con `application: "chrome"` y `confirmed: true`. Consulta `status.audio_route.phase`. `active` indica que Windows confirmó la separación y `restored` confirma la restauración. `requested` y `preparing` indican que la orden está en curso. `waiting` o `pending` indican una restauración pendiente. `failed` indica un error en la operación.

Ejemplo para configurar una fuente:

```json
{
  "action": "set_source",
  "source": "https://www.youtube.com/watch?v=..."
}
```

Ejemplo para reemplazar las hotwords:

```json
{
  "action": "set_hotwords",
  "hotwords": [
    {"phrase": "palabra clave", "threshold": 90},
    {"phrase": "Yojemr", "threshold": 88, "enabled": true}
  ]
}
```

La definición legible por máquinas está en `agent-control.schema.json`.

## Skill reutilizable para Codex

`integrations/codex/auralwarden` contiene la skill distribuible: instrucciones, catálogo versionado, referencia de todas las funciones y un ayudante PowerShell que descubre ejecutables, prefiere una instancia activa inequívoca y consulta sus capacidades antes de enviar órdenes. No instala ni habilita el control local automáticamente. Las funciones exclusivas de interfaz se identifican como tales.

Desde el checkout, `scripts/sync-agent-skill.ps1 -Check` valida la compatibilidad. Con autorización del usuario, `scripts/sync-agent-skill.ps1` instala o actualiza únicamente esta skill en la carpeta de skills del perfil de Codex; `-Destination` permite otro destino. Las nuevas compilaciones portables incluyen una copia en `agent-skill`, sin registrar nada en el equipo del usuario.

En cada versión se contrasta la skill con los protocolos, las acciones/límites y los subcomandos reales. La compilación rechaza un catálogo desfasado. El mantenimiento global del desarrollador es independiente de la publicación y no requiere recompilar el EXE cuando solo cambia esta integración.

## Límites de seguridad y privacidad

- Todas las acciones requieren que el usuario haya habilitado el control y que el cliente posea la credencial local.
- El protocolo no ejecuta comandos, no abre archivos solicitados, no cambia carpetas y no permite leer configuraciones o claves.
- `set_source` acepta HTTP/HTTPS o la demostración local. Las fuentes Windows se seleccionan mediante `select_windows_source`. La selección de archivos arbitrarios permanece en la interfaz.
- Las respuestas de estado eliminan usuario, contraseña, consulta y fragmento de las URL.
- La lectura se limita a 200 transcripciones o alertas por solicitud.
- El canal está asociado a la carpeta, cuenta y sesión de Windows. Admite hasta ocho conexiones simultáneas, un plazo absoluto de cinco segundos, solicitudes de 64 KiB y respuestas de 4 MiB.
- Abrir otra instancia puede restaurar la ventana sin autorización de agentes; esa acción no permite leer datos ni iniciar monitoreo.
- El registro `local-control-audit.json` conserva como máximo 500 resultados y nunca guarda argumentos, enlaces, texto transcrito ni credenciales.
- Cualquier programa ejecutado en la misma cuenta de Windows que pueda leer la carpeta portable podría usar la credencial mientras la opción esté activa. Debe deshabilitarse en equipos compartidos o cuando no se necesite.
