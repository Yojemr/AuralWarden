param([string]$Installer = "")

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
if (-not $Installer) {
    $Installer = Join-Path $projectRoot "outputs\Installer-$version\AuralWarden-$version-Setup.exe"
}
$Installer = (Resolve-Path -LiteralPath $Installer).Path
$workRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot 'work')).TrimEnd('\') + '\'
$testRoot = [IO.Path]::GetFullPath((Join-Path $workRoot ('installer-test-' + [guid]::NewGuid().ToString('N'))))
if (-not $testRoot.StartsWith($workRoot, [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $testRoot)) {
    throw 'Unsafe test directory.'
}
$installation = Join-Path $testRoot 'application'
$personalData = Join-Path $testRoot 'personal-data'
$tempRoot = Join-Path $testRoot 'temp'
New-Item -ItemType Directory -Path $personalData,$tempRoot -Force | Out-Null
$env:TEMP = $tempRoot
$env:TMP = $tempRoot
$env:AURALWARDEN_DATA_DIR = $personalData
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONUTF8 = '1'
$fixtures = @{
    'settings.json' = '{"fixture":"preserve"}'
    'models\fixture\model.bin' = 'synthetic model fixture'
    'sessions\fixture\transcripts\class.txt' = 'Synthetic transcript: keep this file.'
    'sessions\fixture\clips\sample.wav' = 'Synthetic clip: keep this file.'
}
foreach ($relative in $fixtures.Keys) {
    $path = Join-Path $personalData $relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $path) -Force | Out-Null
    [IO.File]::WriteAllText($path, $fixtures[$relative])
}
$before = @{}
foreach ($relative in $fixtures.Keys) { $before[$relative] = (Get-FileHash -LiteralPath (Join-Path $personalData $relative)).Hash }
$registryPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{4C3ED85A-5B7A-4C53-82FB-32A6153B0621}_is1'
$registryBefore = if (Test-Path $registryPath) { Get-ItemProperty $registryPath | ConvertTo-Json -Depth 4 } else { '' }
function Run-TestProcess([string]$Executable, [string[]]$Arguments) {
    $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit(60000)) {
        throw "Test process is still running (PID $($process.Id)); inspect its log before retrying."
    }
    if ($process.ExitCode -ne 0) { throw "Test process failed: $($process.ExitCode)" }
}
$setupArguments = @('/QAISOLATED=1','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="'+$installation+'"'))
Run-TestProcess $Installer ($setupArguments + ('/LOG="'+(Join-Path $testRoot 'install.log')+'"'))
$exe = Join-Path $installation 'AuralWarden.exe'
if (-not (Test-Path -LiteralPath $exe) -or (Test-Path -LiteralPath (Join-Path $installation 'portable.flag'))) {
    throw 'Installed mode was not prepared correctly.'
}
$check = Join-Path $testRoot 'self-check.json'
Run-TestProcess $exe @('--self-check','--self-check-output',('"'+$check+'"'))
$result = Get-Content -LiteralPath $check -Raw | ConvertFrom-Json
if ($result.status -ne 'ok' -or $result.version -ne $version) { throw 'Installed self-check failed.' }
$referenceReadme = (Get-FileHash -LiteralPath (Join-Path $installation 'README.md')).Hash
[IO.File]::WriteAllText((Join-Path $installation 'README.md'), 'Old application file for update test')
[IO.File]::WriteAllText((Join-Path $installation 'user-note.txt'), 'Unknown user file: preserve')
Run-TestProcess $Installer ($setupArguments + ('/LOG="'+(Join-Path $testRoot 'update.log')+'"'))
if ((Get-FileHash -LiteralPath (Join-Path $installation 'README.md')).Hash -ne $referenceReadme) { throw 'Update did not replace the application file.' }
$uninstallers = @(Get-ChildItem -LiteralPath $installation -Filter 'unins*.exe')
if ($uninstallers.Count -ne 1) { throw 'Expected a single uninstaller.' }
Run-TestProcess $uninstallers[0].FullName @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/LOG="'+(Join-Path $testRoot 'uninstall.log')+'"'))
if (Test-Path -LiteralPath $exe) { throw 'Uninstall did not remove the executable.' }
if (-not (Test-Path -LiteralPath (Join-Path $installation 'user-note.txt'))) { throw 'Uninstall removed an unowned file.' }
foreach ($relative in $fixtures.Keys) {
    if ((Get-FileHash -LiteralPath (Join-Path $personalData $relative)).Hash -ne $before[$relative]) {
        throw "Personal fixture changed: $relative"
    }
}
$registryAfter = if (Test-Path $registryPath) { Get-ItemProperty $registryPath | ConvertTo-Json -Depth 4 } else { '' }
if ($registryBefore -ne $registryAfter) { throw 'Isolated QA modified installation registration.' }
[pscustomobject]@{
    Version=$version; Status='ok'; TestRoot=$testRoot; Install=$true; Update=$true; Uninstall=$true
    PersonalDataHashesPreserved=$true; UnownedFilePreserved=$true; NoRegistrationChange=$true
} | ConvertTo-Json
