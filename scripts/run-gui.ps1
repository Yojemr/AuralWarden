param(
    [switch]$Demo
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $venvPython)) {
    throw "Run scripts\setup.ps1 -Profile ui first."
}

$arguments = @("-m", "auralwarden.gui_main")
if ($Demo) {
    $arguments += "--demo"
}

Start-Process -FilePath $venvPython -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden
