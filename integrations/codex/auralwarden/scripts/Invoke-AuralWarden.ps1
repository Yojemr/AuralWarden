param(
    [ValidateSet('discover','capabilities','status','set_source','set_hotwords','start','stop','transcript','alerts','show',
        'list_windows','list_audio_devices','select_windows_source','configure_session','set_stop_timer',
        'create_clip','save_transcript','separate_audio','restore_audio')]
    [string]$Action = 'discover',
    [hashtable]$Parameters = @{},
    [string]$Executable = '',
    [string]$ProjectRoot = '',
    [string]$WorkDirectory = ''
)

$ErrorActionPreference = 'Stop'
if (-not $ProjectRoot) { $ProjectRoot = $env:AURALWARDEN_PROJECT_ROOT }
if (-not $ProjectRoot) {
    $ProjectRoot = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Codex\Proyectos\Herramientas Bot\AuralWarden'
}
$candidates = @()
if (Test-Path -LiteralPath (Join-Path $ProjectRoot 'outputs') -PathType Container) {
    $candidates = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'outputs') -Directory | ForEach-Object {
        if ($_.Name -match '^AuralWarden-(\d+\.\d+\.\d+)$') {
            $candidateVersion = [version]$Matches[1]
            $path = Join-Path $_.FullName 'AuralWarden.exe'
            if (Test-Path -LiteralPath $path -PathType Leaf) {
                [pscustomobject]@{path=[IO.Path]::GetFullPath($path); version=$candidateVersion.ToString()}
            }
        }
    } | Sort-Object @{Expression={[version]$_.version};Descending=$true})
}
if ($env:LOCALAPPDATA) {
    $installed = Join-Path $env:LOCALAPPDATA 'Programs\AuralWarden\AuralWarden.exe'
    if (Test-Path -LiteralPath $installed -PathType Leaf) {
        $candidates += [pscustomobject]@{path=[IO.Path]::GetFullPath($installed);version='installed'}
    }
}
$active = @(Get-Process -Name AuralWarden -ErrorAction SilentlyContinue)
$unknownActive = $false
$resolvedActive = @()
foreach ($process in $active) {
    try {
        if ($process.Path) { $resolvedActive += [IO.Path]::GetFullPath($process.Path) }
        else { $unknownActive = $true }
    } catch { $unknownActive = $true }
}
$activePaths = @($resolvedActive | Select-Object -Unique)
$ambiguous = $activePaths.Count -gt 1 -or $unknownActive
$selected = ''
if ($Executable) {
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf) -or [IO.Path]::GetFileName($Executable) -ine 'AuralWarden.exe') {
        throw 'Elige un AuralWarden.exe local existente.'
    }
    $selected = [IO.Path]::GetFullPath($Executable)
} elseif (-not $ambiguous -and $activePaths.Count -eq 1) {
    $selected = $activePaths[0]
} elseif (-not $ambiguous -and $candidates.Count -gt 0) {
    $selected = $candidates[0].path
}
if ($Action -eq 'discover') {
    [pscustomobject]@{selected=$selected;active_paths=$activePaths;ambiguous=$ambiguous;candidates=$candidates} | ConvertTo-Json -Depth 5
    return
}
if (-not $selected) { throw 'No hay una instalación inequívoca. Usa discover y selecciona -Executable explícitamente.' }
$allowed = @{
    capabilities=@();status=@();start=@();stop=@();show=@()
    set_source=@('source');set_hotwords=@('hotwords');transcript=@('limit');alerts=@('limit')
    list_windows=@('application');list_audio_devices=@('kind');select_windows_source=@('kind','window_id','device')
    configure_session=@('options');set_stop_timer=@('duration_seconds','stop_at_epoch')
    create_clip=@();save_transcript=@();separate_audio=@('application','confirmed');restore_audio=@()
}
foreach ($key in $Parameters.Keys) {
    if ($key -notin $allowed[$Action]) { throw "Campo no admitido para esta acción: $key" }
}
if (-not $WorkDirectory) {
    $WorkDirectory = Join-Path $ProjectRoot 'work\agent-control'
}
$workRoot = [IO.Path]::GetFullPath($WorkDirectory)
New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
$requestFolder = Join-Path $workRoot ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $requestFolder | Out-Null
$utf8 = New-Object Text.UTF8Encoding($false)

function Invoke-ControlRequest([hashtable]$Payload) {
    $request = Join-Path $requestFolder 'request.json'
    $response = Join-Path $requestFolder 'response.json'
    $json = ConvertTo-Json -InputObject $Payload -Depth 12 -Compress
    if ($utf8.GetByteCount($json) -gt 65536) { throw 'La solicitud supera 64 KiB.' }
    [IO.File]::WriteAllText($request, $json, $utf8)
    if (Test-Path -LiteralPath $response) { Remove-Item -LiteralPath $response -Force }
    $client = Start-Process -FilePath $selected -ArgumentList @('--control-request', ('"{0}"' -f $request),
        '--control-output', ('"{0}"' -f $response)) -WindowStyle Hidden -PassThru
    if (-not $client.WaitForExit(20000)) {
        # This is the short-lived request client, never the monitoring process.
        $client.Kill()
        $client.WaitForExit(5000) | Out-Null
        throw 'Resultado incierto: el cliente excedió el plazo. Consulta status antes de repetir la orden.'
    }
    if (-not (Test-Path -LiteralPath $response -PathType Leaf)) { throw 'No se recibió una respuesta JSON; no se reintentó la orden.' }
    if ((Get-Item -LiteralPath $response).Length -gt 4194304) { throw 'Respuesta demasiado grande.' }
    $result = Get-Content -LiteralPath $response -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($result -isnot [pscustomobject] -or $null -eq $result.ok) { throw 'Respuesta local no válida.' }
    return $result
}

try {
    $capabilities = Invoke-ControlRequest @{action='capabilities'}
    if (-not $capabilities.ok) {
        $capabilities | ConvertTo-Json -Depth 16
        return
    }
    if ($Action -eq 'capabilities') { $capabilities | ConvertTo-Json -Depth 16; return }
    if ($Action -notin $capabilities.actions) { throw 'La instancia no anuncia esta acción; no se envió.' }
    $payload = @{action=$Action}
    foreach ($key in $Parameters.Keys) { $payload[$key] = $Parameters[$key] }
    Invoke-ControlRequest $payload | ConvertTo-Json -Depth 16
} finally {
    # Only files generated in this invocation are removed; caller data is untouched.
    foreach ($name in @('request.json','response.json')) {
        $owned = Join-Path $requestFolder $name
        if (Test-Path -LiteralPath $owned -PathType Leaf) { Remove-Item -LiteralPath $owned -Force }
    }
    if (Test-Path -LiteralPath $requestFolder -PathType Container) { Remove-Item -LiteralPath $requestFolder }
}
