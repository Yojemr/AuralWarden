param(
    [ValidateSet("core", "capture", "stt", "cuda", "diarization", "ui", "public", "all")]
    [string]$Profile = "core",
    [string]$Python = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$constraints = Join-Path $projectRoot "requirements-build.lock.txt"
function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}

if (-not (Test-Path $venvPython)) {
    if ($Python) {
        & $Python -m venv (Join-Path $projectRoot ".venv")
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv (Join-Path $projectRoot ".venv")
    } else {
        & python -m venv (Join-Path $projectRoot ".venv")
    }
    Assert-NativeSuccess "Environment creation"
}

& $venvPython -m pip --version 2>$null
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m ensurepip
    Assert-NativeSuccess "pip initialization"
}
$extras = switch ($Profile) {
    "capture" { "dev,capture" }
    "stt" { "dev,stt" }
    "cuda" { "dev,stt,cuda" }
    "diarization" { "dev,diarization" }
    "ui" { "dev,ui" }
    "public" { "dev,desktop-cpu" }
    "all" { "dev,capture,stt,cuda,diarization,ui" }
    default { "dev" }
}
& $venvPython -m pip install --constraint $constraints -e "$projectRoot[$extras]"
Assert-NativeSuccess "Dependency installation"
& $venvPython -c "import importlib.metadata, auralwarden; assert importlib.metadata.version('auralwarden') == auralwarden.__version__"
Assert-NativeSuccess "Installed package verification"

Write-Host "AuralWarden environment is ready ($Profile)."
