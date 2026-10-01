# AuralWarden 1.0.2

Correcciones de estabilidad, detección, privacidad y distribución derivadas de la auditoría previa a publicación. No modifica la función principal: escuchar localmente, avisar por hotwords y conservar clips opcionales.

## Cambios principales

- Captura independiente de la transcripción, con memoria limitada e información sobre retrasos.
- Segunda pasada sin preferencia artificial por las palabras configuradas; deduplicación que conserva términos nuevos.
- Cancelación efectiva de hotwords eliminadas y restricciones de hablante basadas en perfiles realmente comparados.
- Clips con intervalos estables, audio recortado correctamente y comprobación de vídeo decodificable.
- Índices incrementales compatibles con lectura y escritura concurrentes en Windows; segmentos recuperables si falla la finalización.
- Cierre que espera el último fragmento antes de guardar y manejo más robusto de errores y cancelación.
- Subtítulos sin repetición de todo el historial, con contexto temporal limitado.
- Control local con autenticación mutua y límites de tiempo, memoria y conexiones. No requiere claves de API ni transmite su credencial persistente.
- Metadatos de versión coherentes y avisos de dependencias comprobados mediante versiones y hashes fijos.

## Validación

203 pruebas automatizadas aprobadas en Windows. Los casos de clips MP4 se ejecutaron repetidamente y una revisión independiente comprobó el alcance sensible de control local y texto externo.

La carpeta portable es CPU; CUDA continúa como componente opcional separado. Las versiones anteriores y los datos personales no se incluyen ni se eliminan al preparar esta entrega. El ejecutable no está firmado.

## Publicación

Esta entrega se prepara para uso y validación local. La publicación de binarios requiere completar las fuentes correspondientes y procedencia de bibliotecas nativas, además de la lista de `RELEASE_CHECKLIST.md`. La recopilación de textos de licencia no certifica por sí sola ese cumplimiento. No se ha validado en un segundo computador ni en una sesión prolongada de voz real con este parche.
