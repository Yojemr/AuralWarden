# AuralWarden 1.4.0 — Instalación, almacenamiento y temporizador

## Novedades

- Instalador por usuario y edición portable. El instalador no necesita administrador ni instala CUDA, VB-CABLE o modelos automáticamente.
- Actualizaciones y desinstalación conservando configuración, modelos y evidencia en la carpeta de datos. El instalador solicita cerrar AuralWarden si la edición instalada está abierta; no la cierra por la fuerza.
- Temporizador de detención por duración o fecha/hora, con estado visible y acceso desde la bandeja. Finaliza mediante la detención habitual, conservando la transcripción para guardarla y restaurando el audio separado. Los clips pendientes pueden quedar incompletos si se detiene antes del intervalo posterior.
- Gestor de almacenamiento: tamaños por categoría, espacio libre, filtros y envío manual de clips, grabaciones y transcripciones a la Papelera. No elimina automáticamente ni permite borrar configuración, modelos, componentes o recuperación.
- Reutilización de una carpeta de datos anterior sin duplicar su contenido, disponible en la edición instalada y aplicada al siguiente inicio.
- Actualizaciones seleccionadas de captura web, conexiones HTTPS, pycaw y comprobaciones de GitHub. Qt y CUDA mantienen sus versiones verificadas.

## Límites

El temporizador solo funciona mientras AuralWarden está abierta, incluso minimizada; no despierta el equipo ni se conserva después de cerrarla. La duración usa un reloj monotónico; la fecha/hora usa la hora de Windows y se verifica al reanudar. No se garantiza precisión al segundo durante una suspensión o bloqueo del sistema. No inicia una grabación por sí solo.

El análisis de almacenamiento se limita a la carpeta de datos actual, 20.000 archivos y 15 segundos. Omite enlaces y carpetas inaccesibles y muestra si el resultado es parcial. Los tamaños son lógicos, no una promesa del espacio físico liberado al existir enlaces duros; la Papelera puede conservar espacio hasta vaciarse desde Windows. No se vacía automáticamente.

La navegación sincronizada entre frases y vídeo no forma parte de esta versión. La validación en otro equipo y las sesiones prolongadas de esta candidata siguen pendientes.

## Distribución local

Consulta [Instalación](INSTALLATION.md) para instalación, actualización y reutilización de datos. La candidata no está firmada digitalmente y no se ha publicado en GitHub. La distribución binaria pública requiere completar las fuentes correspondientes de sus bibliotecas nativas; esta compilación local no cambia ese requisito.
