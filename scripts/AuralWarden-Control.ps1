param(
    [Parameter(Mandatory = $true)]
    [string]$Request,
    [string]$Output = ""
)

$ErrorActionPreference = "Stop"
$toolRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$executable = Join-Path $toolRoot "AuralWarden.exe"
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "AuralWarden-Control.ps1 debe permanecer junto a AuralWarden.exe."
}
$requestPath = [System.IO.Path]::GetFullPath($Request)
if (-not (Test-Path -LiteralPath $requestPath -PathType Leaf)) {
    throw "No existe el archivo de solicitud: $requestPath"
}
$temporaryOutput = -not [bool]$Output
if ($temporaryOutput) {
    $Output = Join-Path ([System.IO.Path]::GetTempPath()) ("auralwarden-control-response-{0}.json" -f [guid]::NewGuid().ToString("N"))
}
$outputPath = [System.IO.Path]::GetFullPath($Output)
$process = Start-Process -FilePath $executable -ArgumentList @(
    "--control-request", ('"{0}"' -f $requestPath),
    "--control-output", ('"{0}"' -f $outputPath)
) -WindowStyle Hidden -Wait -PassThru
if (Test-Path -LiteralPath $outputPath -PathType Leaf) {
    $response = Get-Content -LiteralPath $outputPath -Raw
    if ($temporaryOutput) {
        Remove-Item -LiteralPath $outputPath -Force
    }
    $response
}
exit $process.ExitCode
