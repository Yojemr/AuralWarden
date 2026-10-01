# Compatibilidad de hardware

AuralWarden no presupone un procesador ni una tarjeta gráfica concretos. Al iniciar una sesión real, analiza localmente los recursos disponibles y crea un plan de inferencia. Esta información no sale del equipo.

Desde 0.7.0, la adaptación durante la sesión utiliza muestras consecutivas de CPU, GPU, RAM y VRAM. Una subida aislada no cambia el perfil; la carga debe mantenerse y la recuperación usa un margen diferente para evitar oscilaciones. El modelo permanece cargado: se ajustan el haz, las segundas pasadas no esenciales y, en whisper.cpp, los hilos.

## Selección automática

| Equipo detectado | Motor | Dispositivo | Precisión inicial | Modelos preferidos |
|---|---|---|---|---|
| NVIDIA con CUDA local y al menos 6 GB de VRAM | faster-whisper | CUDA | float16 | large-v3-turbo, small, base |
| NVIDIA con menos VRAM | faster-whisper | CUDA | int8_float16 | small, base, tiny |
| CPU de más de 4 núcleos | faster-whisper | CPU | int8 | base, small, tiny |
| CPU de hasta 4 núcleos o modo Bajo consumo | faster-whisper | CPU | int8 | tiny, base, small |
| Componente whisper.cpp CPU completo | whisper.cpp | CPU | cuantización del modelo | modelo GGML/GGUF indicado |
| GPU AMD/Intel y componente whisper.cpp Vulkan declarado | whisper.cpp | Vulkan | cuantización del modelo | modelo GGML/GGUF indicado |

La selección usa únicamente modelos que ya estén disponibles localmente. Si ninguno de los candidatos está instalado, la interfaz explica que falta el modelo en vez de descargarlo o cambiar rutas sin permiso.

## Modos de rendimiento

- **Automático:** decide según la capacidad detectada y deja actuar al control dinámico de carga.
- **Precisión máxima:** favorece modelos mayores cuando la memoria y el procesador lo permiten.
- **Equilibrado:** limita los hilos y conserva las funciones de precisión configuradas.
- **Bajo consumo:** usa CPU `int8`, un máximo de dos hilos, ventanas más largas, menos solapamiento y omite la diarización y las segundas pasadas no esenciales durante esa sesión.

Las detecciones dudosas cercanas a una hotword conservan prioridad incluso cuando el sistema reduce carga.

## Motores y paquetes

`faster-whisper` funciona como motor principal y mantiene un camino CPU común. El portable público no distribuye las bibliotecas NVIDIA: CUDA se prepara de forma opcional desde la aplicación, con confirmación de sus condiciones y verificación de archivos. El instalador de desarrollo conserva el perfil `cuda` y el constructor añade `-WithCuda` únicamente a variantes locales específicas.

`whisper.cpp` se integra como componente externo versionable. AuralWarden valida la firma SHA-256, impide que un archivo comprimido escriba fuera de su destino y mantiene el componente dentro de `data/runtime/components`. Los modelos GGML/GGUF permanecen separados del ejecutable.

La versión 0.4.0 incluye el adaptador y la configuración Vulkan, pero no distribuye un binario Vulkan oficial para Windows. Para usar AMD o Intel con GPU debe seleccionarse un ejecutable compilado con Vulkan y declararse esa aceleración en Preferencias. Si solo se dispone del paquete CPU, AuralWarden lo trata como CPU.

## Diagnóstico

En **Preferencias > Reconocimiento**, el botón **Analizar** muestra núcleos, RAM, adaptadores identificados y el plan recomendado. La autocomprobación del portable acepta tanto CUDA como CPU; CUDA dejó de ser un requisito de arranque.
