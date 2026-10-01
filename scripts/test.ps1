$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $venvPython)) {
    throw "Run scripts\setup.ps1 first."
}

$testRoot = Join-Path $projectRoot "work\tests-$([guid]::NewGuid().ToString('N'))"
& $venvPython -B -m pytest -p no:cacheprovider --basetemp $testRoot "$projectRoot\tests"
if ($LASTEXITCODE -ne 0) { throw "AuralWarden tests failed (exit $LASTEXITCODE)." }
