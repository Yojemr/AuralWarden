# Instalación y actualización

## Edición instalada

Ejecuta `AuralWarden-<versión>-Setup.exe` cuando esté disponible para esa versión. Instala únicamente el programa para la cuenta actual en `%LOCALAPPDATA%\Programs\AuralWarden`, salvo que elijas otra carpeta. Crea un acceso en el menú Inicio; el acceso al escritorio es opcional. No modifica el PATH, los dispositivos de audio ni la seguridad de arranque. No solicita reiniciar Windows.

Los datos predeterminados se guardan por separado en `%LOCALAPPDATA%\AuralWarden`. Los modelos se preparan desde el asistente al primer uso, mostrando su tamaño y verificando integridad. CUDA y VB-CABLE permanecen opcionales y separados.

Para actualizar, detén el monitoreo, guarda lo que necesites y cierra AuralWarden. Ejecuta el nuevo instalador sobre la misma instalación. Su identificador permanece constante entre versiones: no hay que reconstruir la receta del instalador desde cero ni volver a descargar modelos compatibles. Los datos no forman parte de los archivos que reemplaza el instalador.

La desinstalación retira el programa y sus accesos; conserva los modelos, configuración, perfiles, notas y evidencia. No elimina archivos externos ni vacía la Papelera.

## Reutilizar datos de una edición portable

1. Detén y cierra la edición portable anterior. Guarda la transcripción antes de salir.
2. En la edición instalada abre **Menú > Reutilizar carpeta de datos**.
3. Selecciona su carpeta `data`, que debe contener `settings.json`, y confirma.
4. Cierra y vuelve a abrir la edición instalada. No se reinicia automáticamente.

El programa escribe una referencia local `data-location.json` junto al ejecutable. No duplica ni mueve las grabaciones o modelos. No elimines la carpeta anterior mientras se utilice; conserva también las rutas externas que aparezcan en su configuración. No abras dos versiones simultáneamente sobre esos datos. Si la carpeta deja de estar disponible, el programa informa del problema en lugar de crear silenciosamente una configuración vacía.

Para volver a la ubicación predeterminada, con AuralWarden cerrada conserva una copia de esa referencia fuera de la instalación y retírala de junto al ejecutable. Los datos originales permanecen intactos. La variable avanzada `AURALWARDEN_DATA_DIR` tiene prioridad sobre la referencia.

## Edición portable

Conserva toda la carpeta, incluido el marcador oculto `portable.flag`. Utiliza su propia carpeta `data` y no necesita instalación. No copies solo el ejecutable. Las versiones anteriores no se eliminan automáticamente al preparar la candidata.

## Construir el instalador

Se utiliza Inno Setup 7.1.1 oficial. El compilador de desarrollo puede prepararse en modo portable con `/PORTABLE=1 /CURRENTUSER /NOICONS` dentro de `work/tools/InnoSetup`. Ese modo no registra la herramienta ni crea asociaciones. El compilador no se incluye con AuralWarden y no es necesario para sus usuarios.

```powershell
.\scripts\build-portable.ps1 -WithCapture -WithStt -WithDiarization -WithUi -BundleFfmpeg -VersionedFolder -PreservePreviousVersions
.\scripts\build-installer.ps1 -Compiler .\work\tools\InnoSetup\ISCC.exe
```

La receta toma el número de `VERSION`, rechaza paquetes con datos locales o enlaces y genera `outputs/Installer-<versión>/AuralWarden-<versión>-Setup.exe`. No sobrescribe un instalador ya existente y calcula su SHA-256. El modo portable y la referencia de datos personales se excluyen del instalador. No modifica el código ni crea una Release automáticamente.

El parámetro de prueba `/QAISOLATED=1`, junto con `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=<carpeta-de-prueba>`, permite probar extracción y desinstalación sin registrar AuralWarden, crear accesos ni abrir el programa. Debe utilizarse únicamente con una carpeta de prueba vacía y datos sintéticos; el modo normal sigue siendo el destinado a usuarios.

Las compilaciones locales no están firmadas digitalmente. La publicación binaria necesita además completar la correspondencia de fuentes de sus dependencias nativas. No basta con crear el instalador para dar por terminada esa preparación.
