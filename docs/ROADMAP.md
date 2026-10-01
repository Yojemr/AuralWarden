# Hoja de ruta

## 0.1 — Primera versión local funcional

- Captura Streamlink/FFmpeg y audio PCM.
- Búfer circular, sesiones y registros.
- Adaptador `faster-whisper`, VAD y hotwords.
- Segunda pasada, fusión temporal y clips WAV.
- Contexto, probabilidades por palabra y estabilización de solapamientos.
- Diarización local, etiquetas estables y renombrado manual en backend.
- Recursos, consola y pruebas básicas.
- Interfaz de escritorio basada en la referencia seleccionada.
- Transcripción temporal, actividad reciente y configuración.
- Históricos breves de recursos y bandeja de Windows.
- Notificaciones locales, sonidos y previsualización ligera.

## 0.2 — Evidencia audiovisual y segundo plano

- Búfer segmentado y temporal de vídeo.
- Clips MP4 con pre-roll, post-roll, vídeo y audio.
- Creación asíncrona para mantener activa la transcripción.
- Vigilancia desde la bandeja con la ventana oculta.
- Controles y estado separados para evidencia WAV y MP4.
- Detección automática y selección sencilla de modelos locales.
- Accesos directos separados a clips de vídeo, clips de audio y transcripciones.

## 0.3 — Fiabilidad y fuentes

- Descarga administrada de `large-v3-turbo` y prueba controlada completadas.
- Prueba real breve en español completada; quedan pruebas prolongadas y evaluación cuantitativa.
- Reconexión de emisiones y reloj estable.
- Fuentes de audio del sistema y micrófono con selección de dispositivo.
- Adaptación automática para YouTube, Twitch, Kick, radio y protocolos directos compatibles.
- Monitorización silenciosa reversible con restauración permanente al detectar una hotword.
- Medición de latencia, falsos negativos y falsos positivos.

## 0.4 — Compatibilidad de hardware

- Detección automática de CPU, RAM, GPU, VRAM y CUDA.
- Planes automáticos de motor, modelo, precisión e hilos.
- Modos de precisión, equilibrio y bajo consumo.
- Respaldo CPU universal y dependencias CUDA separadas.
- Adaptador modular `whisper.cpp` para CPU y Vulkan.
- Instalación segura y versionada de componentes opcionales.
- Queda pendiente empaquetar y validar un componente Vulkan de Windows antes de declararlo incluido.

## 0.5 — Reconocimiento híbrido y conservación

- Subtítulos de YouTube como fuente independiente cuando estén disponibles.
- Fusión temporal entre Whisper y subtítulos.
- Grabación completa de vídeo como opción independiente.
- Recuperación de transcripciones interrumpidas.
- Migración portable de preferencias y modelos sin duplicar almacenamiento.

## 0.6 — Hablantes avanzados

- Corrección interactiva y consolidación final de hablantes.
- Perfiles de voz opcionales administrados por el usuario.
- Alertas por hotword condicionadas a un perfil de voz elegido.

## 0.7 — Experiencia de escritorio

- Presets incluidos y personales sin conservar enlaces ni dispositivos privados.
- Historial filtrable de alertas y apertura directa de evidencia.
- Accesibilidad y escalado adicional para pantallas pequeñas.
- Adaptación dinámica estabilizada con carga sostenida, histéresis y recuperación gradual.

## 0.8 — Rendimiento y fiabilidad

- Protocolo local opcional, autenticado y documentado para agentes y automatizaciones.
- Estado en vivo, edición de enlace/hotwords, inicio, detención y lecturas recientes sin control del mouse.
- Redacción de parámetros privados en estados y diagnósticos externos.
- Auditoría local acotada sin argumentos, texto ni credenciales.
- Evaluación prolongada del ajuste dinámico durante cargas reales mixtas.
- Recuperación de sesiones y diagnóstico de fallos.
- Sincronización estricta del estado visible, la captura en segundo plano, la bandeja y los archivos `runtime-status.json`/`session.json`, incluso al restaurar la ventana o finalizar un directo.
- Pruebas prolongadas de varias horas.

## 0.9 — Distribución portable

- Ejecutable reproducible para Windows completado.
- Administración local de FFmpeg, Streamlink y modelos completada.
- Descarga guiada de modelos dentro de `data/models`, con revisión, tamaño, SHA-256 y selección automática completada.
- Creación automática de toda la estructura local durante un primer inicio limpio completada.
- Distribución pública base CPU y CUDA opcional separado completadas y validadas en el equipo de desarrollo.

## 0.10 — Privacidad y publicación

- Auditoría de seguridad y privacidad del código fuente realizada; cualquier hallazgo se corrige y conserva como informe antes de la entrega.
- Documentación de contribución, licencia y componentes de terceros completada.
- Prueba desde una extracción nueva y aislada de Windows; no estuvo disponible un segundo computador para validación independiente.

## 0.11 — Candidato estable

- Correcciones finales y compatibilidad hacia atrás completadas.
- Preparación del repositorio público completada.

## 1.0 — Primera versión pública

- Flujo completo validado localmente y paquete portable CPU preparado.
- ZIP de publicación autosuficiente con instalador interno capaz de descargar modelos a una carpeta local que AuralWarden detecta sin configuración manual.
- Componentes CUDA separados y opcionales; ninguna instalación de controladores se realiza desde AuralWarden.
- En la siguiente versión, el análisis de hardware recomendará explícitamente instalar CUDA cuando detecte una GPU NVIDIA compatible, aunque el componente todavía no esté preparado, y mostrará por separado la configuración ideal y la disponible en ese momento.
