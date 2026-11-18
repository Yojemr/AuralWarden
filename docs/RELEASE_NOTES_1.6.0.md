# AuralWarden 1.6.0

## Control local de sesiones

Los clientes autenticados pueden consultar ventanas de una aplicación concreta, elegir una ventana o dispositivo de audio, configurar diarización y grabación, programar la detención, solicitar un clip manual y guardar una transcripción TXT en la carpeta correspondiente.

## Separación de audio por aplicación

La orden actúa sobre la aplicación monitoreada en **Audio de aplicación**. Requiere que llegue señal y que Windows disponga de un único VB-CABLE estándar. El cambio afecta al audio de la aplicación completa, incluidas sus pestañas y ventanas. Las otras aplicaciones conservan sus salidas. AuralWarden restaura la salida anterior al recibir una hotword, detener la sesión, cerrar la aplicación o recibir una orden de restauración.

El estado de la ruta distingue una solicitud en curso de los estados verificados de separación y restauración. La [referencia del control local](AGENT_CONTROL.md) detalla los parámetros y estados.

## Distribución

Los archivos de GitHub contienen el código fuente. La guía del repositorio explica cómo ejecutar AuralWarden o generar una carpeta portable desde Windows.
