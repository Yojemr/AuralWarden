# Security

## Sensitive data

AuralWarden no requiere claves de API para su núcleo local. No deben incorporarse al repositorio cookies de navegador, tokens, archivos `.env`, grabaciones, transcripciones privadas ni modelos descargados.

Las rutas y nombres de archivos privados se excluyen mediante `.gitignore`. AuralWarden no ofrece campos para claves de API, pero `settings.json` puede contener un enlace firmado con parámetros temporales y debe tratarse como privado.

Los procesos externos se ejecutan mediante listas de argumentos y sin intérprete de comandos. Las fuentes remotas se entregan a Streamlink y FFmpeg sin construir comandos de texto ejecutables.

Los datos de sesión se escriben fuera del código fuente y sus carpetas están excluidas de Git. Antes de publicar el repositorio debe comprobarse que no se hayan añadido manualmente grabaciones, transcripciones, cookies o modelos.

## Local agent control

El protocolo para agentes está desactivado por defecto, usa IPC local de Windows y exige una credencial aleatoria separada de cualquier API externa. Su lista de órdenes es cerrada: no ejecuta comandos, no lee rutas indicadas por el cliente y no devuelve configuración, tokens ni rutas de evidencia. Los enlaces se depuran antes de aparecer en respuestas o estados externos.

La credencial `local-control.json`, su auditoría y los archivos de solicitud o respuesta del usuario no deben publicarse. Desactivar la opción revoca la credencial existente. En un equipo compartido, otro proceso con la misma identidad de Windows y acceso a la carpeta puede usarla mientras permanezca habilitada.

## Reporting

Cuando el repositorio se publique, utiliza **Security > Report a vulnerability** para comunicar el problema de forma privada. Si esa opción todavía no está habilitada, consulta el perfil del responsable y solicita un canal privado sin incluir detalles técnicos sensibles en una incidencia pública.

Incluye la versión afectada, el impacto observado y pasos mínimos de reproducción con datos sintéticos. No adjuntes grabaciones, transcripciones, cookies, credenciales, enlaces firmados ni perfiles de voz reales.
