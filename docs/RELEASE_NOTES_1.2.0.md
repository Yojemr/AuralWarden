# AuralWarden 1.2.0

## Separar el audio sin perder la captura

La fuente **Audio de aplicación** incorpora **Separar audio**. Envía la aplicación completa a VB-CABLE estándar, mantiene su captura y permite que las demás aplicaciones sigan usando sus salidas habituales. Una hotword solicita recuperar la salida anterior y la deja audible; no vuelve a separarla automáticamente.

El cable es opcional: la captura normal no requiere instalarlo. Su asistente descarga únicamente el paquete estándar oficial de 64 bits, verifica SHA-256 y abre el instalador bajo autorización administrativa del usuario. No instala Voicemeeter ni otros productos y no reinicia Windows automáticamente. El controlador permanece instalado al cerrar AuralWarden y no está incluido dentro del portable.

## Recuperación y controles

- Confirmación del alcance y necesidad de señal antes de separar.
- Comprobación de la salida real, además de la preferencia indicada por Windows.
- Botón y acción de bandeja para restaurar; recuperación al detener o cerrar.
- Auxiliar independiente que intenta restaurar ante fallos de AuralWarden, con valores originales guardados antes del cambio.
- Respeto de cambios externos, validación de identidad y exclusión de auxiliares duplicados.
- Estado **Restauración pendiente** cuando se necesita abrir de nuevo la aplicación original o corregir su salida interna.
- Conservación recuperable de los dispositivos predeterminados anteriores a la instalación.
- Recuperación probada ante el cierre abrupto de un propietario sintético, sin modificar aplicaciones del usuario.

## Compatibilidad

Se comprobó el recorrido sintético completo y una prueba real simultánea de 20 segundos con Chrome/Meet y Brave en el Windows 10 del equipo de desarrollo. Chrome se envió al cable y siguió capturándose en memoria, Brave mantuvo los altavoces y Chrome recuperó su salida original al terminar. El usuario confirmó el resultado auditivo. Las preferencias de Brave y los dispositivos predeterminados permanecieron sin cambios. No se guardó contenido de la reunión ni de la serie. La suite local de 263 pruebas fue aprobada.

El enrutamiento usa una interfaz interna de Windows y no se garantiza para todos los programas o futuras compilaciones. La aplicación vigilada debe respetar la selección de salida de Windows; si no lo hace, se intenta restaurar y se informa el fallo. Si se cerró antes de recuperar el audio, puede requerirse abrirla y reproducir audio. En Chrome el alcance puede incluir otras pestañas y ventanas. El vídeo continúa teniendo el alcance y las limitaciones de la ventana seleccionada.

## Distribución

La publicación de GitHub incluye únicamente el código fuente, sin ejecutables ni instaladores de terceros adjuntos. El portable público queda pendiente de completar la preparación de fuentes correspondientes de las bibliotecas nativas redistribuidas.

La carpeta ejecutable validada localmente se conserva por separado, sin crear un ZIP para esta publicación. No incluye modelos, CUDA, datos personales ni contenido capturado. La captura y las funciones de transcripción y alertas anteriores se mantienen.
