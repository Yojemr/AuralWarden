param(
    [string]$Destination = '',
    [switch]$Check
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $projectRoot 'integrations\codex\auralwarden'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Usa el entorno del proyecto para validar antes de instalar la skill.' }
& $python (Join-Path $PSScriptRoot 'check-agent-skill.py')
if ($LASTEXITCODE -ne 0) { throw 'La skill no coincide con la aplicación; no se instaló.' }
if ($Check) { return }
if (-not $Destination) {
    $codexRoot = $env:CODEX_HOME
    if (-not $codexRoot) { $codexRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }
    $Destination = Join-Path $codexRoot 'skills\auralwarden'
}
$destinationRoot = [IO.Path]::GetFullPath($Destination)
if ([IO.Path]::GetFileName($destinationRoot.TrimEnd('\','/')) -ne 'auralwarden') { throw 'El destino debe ser la carpeta auralwarden.' }
if ($destinationRoot.TrimEnd('\','/') -eq [IO.Path]::GetFullPath($source).TrimEnd('\','/')) { throw 'El destino no puede ser la fuente.' }
if (Test-Path -LiteralPath $destinationRoot) {
    $item = Get-Item -LiteralPath $destinationRoot
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'No se instala sobre una carpeta enlazada.' }
    $installedSkill = Join-Path $destinationRoot 'SKILL.md'
    if (-not (Test-Path -LiteralPath $installedSkill) -or
            -not ((Get-Content -LiteralPath $installedSkill -Raw) -match '(?m)^name: auralwarden\s*$')) {
        throw 'El destino contiene otros datos; no se reemplazó.'
    }
}
$files = @(Get-ChildItem -LiteralPath $source -File -Recurse)
$sourcePrefix = [IO.Path]::GetFullPath($source).TrimEnd('\') + '\'
foreach ($file in $files) {
    $relative = $file.FullName.Substring($sourcePrefix.Length)
    $target = Join-Path $destinationRoot $relative
    $cursor = [IO.Path]::GetDirectoryName($target)
    while ($cursor -and $cursor.Length -ge $destinationRoot.Length) {
        if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Una carpeta del destino es un enlace; no se instaló.'
        }
        if ($cursor -eq $destinationRoot) { break }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    if ((Test-Path -LiteralPath $target) -and ((Get-Item -LiteralPath $target).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Un archivo del destino es un enlace; no se reemplazó.'
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
    Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    if ((Get-FileHash -LiteralPath $file.FullName).Hash -ne (Get-FileHash -LiteralPath $target).Hash) {
        throw "La copia no coincide: $relative"
    }
}
Write-Host "Skill instalada y verificada: $destinationRoot"
