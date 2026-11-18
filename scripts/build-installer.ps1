param(
    [string]$Compiler = "",
    [string]$PackageRoot = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$version = (Get-Content -LiteralPath (Join-Path $projectRoot "VERSION") -Raw).Trim()
if (-not $Compiler) {
    $Compiler = Join-Path $projectRoot "work\tools\InnoSetup\ISCC.exe"
}
if (-not (Test-Path -LiteralPath $Compiler -PathType Leaf)) {
    throw "Indica -Compiler con la ruta al compilador oficial ISCC.exe de Inno Setup. No se instala automáticamente."
}
if (-not $PackageRoot) {
    $PackageRoot = Join-Path $projectRoot "outputs\AuralWarden-$version"
}
$PackageRoot = (Resolve-Path -LiteralPath $PackageRoot).Path
foreach ($required in @("AuralWarden.exe", "runtime", "docs", "CHANGELOG.md", "LICENSE")) {
    if (-not (Test-Path -LiteralPath (Join-Path $PackageRoot $required))) {
        throw "Paquete incompleto: falta $required"
    }
}
$metadata = @(Get-ChildItem -LiteralPath (Join-Path $PackageRoot 'runtime') -Directory -Filter 'auralwarden-*.dist-info')
if ($metadata.Count -ne 1) { throw "No se encontraron metadatos únicos de AuralWarden." }
$metadataText = Get-Content -LiteralPath (Join-Path $metadata[0].FullName 'METADATA') -Raw
if ($metadataText -notmatch "(?m)^Version: $([regex]::Escape($version))\r?$" ) {
    throw "La versión compilada no coincide con VERSION."
}
foreach ($private in @("data", "models", "recordings", "clips", "transcripts", "local-control.json", "startup-error.log", "data-location.json")) {
    if (Test-Path -LiteralPath (Join-Path $PackageRoot $private)) {
        throw "El paquete contiene datos locales: $private. Construye una carpeta portable nueva y limpia."
    }
}
$entries = @(Get-ChildItem -LiteralPath $PackageRoot -Force -Recurse)
if ((Get-Item -LiteralPath $PackageRoot).Attributes -band [IO.FileAttributes]::ReparsePoint -or
    @($entries | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) {
    throw "No se empaquetan enlaces o uniones."
}
$releaseHeading = "## [$version]"
if (-not (Get-Content -LiteralPath (Join-Path $PackageRoot "CHANGELOG.md") -Raw).Contains($releaseHeading)) {
    throw "El paquete no documenta la versión solicitada."
}
$outputRoot = Join-Path $projectRoot "outputs\Installer-$version"
New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
$installer = Join-Path $outputRoot "AuralWarden-$version-Setup.exe"
if (Test-Path -LiteralPath $installer) {
    throw "El instalador ya existe; no se sobrescribe: $installer"
}
& $Compiler "--define=AppVersion=$version" "--define=PackageRoot=$PackageRoot" "--define=OutputRoot=$outputRoot" (Join-Path $projectRoot "installer\AuralWarden.iss")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $installer -PathType Leaf)) {
    throw "La compilación del instalador no terminó correctamente."
}
Get-FileHash -LiteralPath $installer -Algorithm SHA256
