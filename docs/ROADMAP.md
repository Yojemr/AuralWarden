# Hoja de ruta

## 1.6.0 — Control local ampliado

- Selección de ventanas y dispositivos mediante el protocolo local.
- Separación y restauración de audio de la aplicación monitoreada con VB-CABLE.
- Configuración de sesión, temporizador, clips manuales y exportación de transcripciones.

## 1.5.0 — Revisión audiovisual (candidata local)

- Reproductor local bajo demanda en la biblioteca, con saltos desde fragmentos y por tiempo.
- Resaltado temporal, desplazamiento manual y conservación de búsqueda y selección.
- Índices temporales para nuevas grabaciones completas, con detección de intervalos sin grabación y ajuste manual para archivos antiguos.
- Exportación MP4/WAV cancelable sin sobrescribir originales, con recursos de codificación acotados.
- Entrega portable; la preparación del instalador 1.4.1 no forma parte de esta etapa.

## 1.4.1 — Presentación del texto (parche local)

- Párrafos justificados en todas las secciones de lectura y ayuda.
- «Acerca de» redimensionable y rutas completas con acceso a los avisos de terceros.
- Sin cambios en el motor de reconocimiento ni en la captura.

## 1.4.0 — Instalación y actualizaciones (candidata local)

- Receta reutilizable para generar el instalador de Windows en futuras versiones.
- Instalación y actualización conservando modelos, configuración, clips y transcripciones.
- Componentes opcionales separados y preparación de la distribución binaria pública.
- Temporizador de detención por duración o fecha/hora, sin apagado del equipo.
- Inventario de almacenamiento y eliminación manual recuperable con datos protegidos.
- Reutilización de datos de una carpeta anterior sin duplicación.
- Pendientes para publicar: correspondencia de fuentes nativas y validación prolongada de la candidata.

## 1.3.0 — Revisión de sesiones

- Búsqueda dentro de la transcripción abierta y navegación por coincidencias.
- Marcadores con hora y nota, sin editar los originales.
- Clips manuales sin hotwords, usando los intervalos configurados y el reloj de captura.
- Migración de notas y pruebas de límites, concurrencia y continuidad de la detección automática.

## 1.2.0 — Separación opcional de audio

- VB-CABLE estándar opcional, preparado desde la aplicación con descarga verificada y sin productos adicionales.
- Enrutamiento confirmado por la sesión real, restauración permanente por hotword y recuperación independiente ante fallos.
- Conservación de preferencias originales, respeto de cambios externos y recuperación pendiente visible si la aplicación vigilada se cerró.
- Prueba sintética completa y separación simultánea de Chrome/Meet y Brave comprobadas localmente, incluida restauración y confirmación auditiva del usuario.

## 1.1.0 — Audio por aplicación

- Selección explícita de una aplicación y captura nativa de su árbol de procesos.
- Transcripción, hotwords y clips mediante el mismo motor existente; vídeo de la ventana opcional.
- Identidad de proceso validada, auxiliar aislado, memoria acotada y sin cambio automático al audio general.
- Captura real breve comprobada con Chrome/Meet en Windows 10 y aislamiento comprobado con fuentes sintéticas independientes.
- El silencio del mezclador suprime la captura en el equipo probado; la separación mediante salida virtual se incorpora en 1.2.0.

## 1.0.3 — Vídeo de ventanas locales

- Fuente integrada «Ventana + audio del PC», con selección explícita de una ventana.
- Vídeo y audio sin silenciar Windows, con transcripción local y clips por hotwords.
- Grabación completa opcional, segmentos recuperables y proceso nativo aislado.
- Sin captura automática del escritorio ni cambio de ventana cuando se cierra la seleccionada.

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
