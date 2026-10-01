param(
    [switch]$RunTests
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$failures = [System.Collections.Generic.List[string]]::new()

function Add-Failure {
    param([string]$Message)
    $script:failures.Add($Message)
}

$requiredFiles = @(
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    "README.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "NOTICE",
    "SECURITY.md",
    "VERSION",
    "pyproject.toml",
    "requirements-build.lock.txt",
    "docs\GITHUB_PUBLISHING.md",
    "docs\RELEASE_CHECKLIST.md",
    "docs\RELEASE_NOTES_1.0.2.md",
    ".github\CODEOWNERS",
    ".github\dependabot.yml",
    ".github\release.yml",
    ".github\workflows\tests.yml",
    ".github\workflows\codeql.yml",
    ".github\ISSUE_TEMPLATE\bug_report.yml",
    ".github\ISSUE_TEMPLATE\feature_request.yml",
    ".github\ISSUE_TEMPLATE\question.yml"
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $relativePath))) {
        Add-Failure "Falta el archivo público requerido: $relativePath"
    }
}

$version = (Get-Content -LiteralPath (Join-Path $projectRoot "VERSION") -Raw).Trim()
$pyproject = Get-Content -LiteralPath (Join-Path $projectRoot "pyproject.toml") -Raw
$packageInit = Get-Content -LiteralPath (Join-Path $projectRoot "src\auralwarden\__init__.py") -Raw
$pyprojectMatch = [regex]::Match($pyproject, '(?m)^version\s*=\s*"([^"]+)"')
$packageMatch = [regex]::Match($packageInit, '(?m)^__version__\s*=\s*"([^"]+)"')

if (-not $pyprojectMatch.Success -or $pyprojectMatch.Groups[1].Value -ne $version) {
    Add-Failure "La versión de pyproject.toml no coincide con VERSION ($version)."
}
if (-not $packageMatch.Success -or $packageMatch.Groups[1].Value -ne $version) {
    Add-Failure "La versión del paquete no coincide con VERSION ($version)."
}

Push-Location $projectRoot
try {
    $candidateFiles = @(& git -c "safe.directory=$($projectRoot.Replace('\', '/'))" ls-files --cached --others --exclude-standard)
    if ($LASTEXITCODE -ne 0) {
        throw "Git no pudo enumerar los archivos candidatos."
    }
} finally {
    Pop-Location
}

$forbiddenRoots = '^(?:data|outputs|Archivo|work|\.venv|clips|recordings|transcripts|models|logs|cache)/'
$textExtensions = @(
    ".cfg", ".ini", ".json", ".md", ".ps1", ".py", ".toml", ".txt",
    ".yaml", ".yml"
)
$textNamesWithoutExtension = @(
    ".editorconfig", ".gitattributes", ".gitignore", "LICENSE", "NOTICE", "VERSION"
)
$sensitivePatterns = @(
    @{ Name = "ruta local de perfil de Windows"; Pattern = '(?i)[A-Z]:\\Users\\[^\\\r\n]+\\' },
    @{ Name = "clave privada"; Pattern = '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----' },
    @{ Name = "token de GitHub"; Pattern = '(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})' },
    @{ Name = "clave de OpenAI"; Pattern = 'sk-[A-Za-z0-9_-]{20,}' },
    @{ Name = "cabecera Bearer"; Pattern = '(?i)Authorization\s*:\s*Bearer\s+[A-Za-z0-9._~-]{12,}' }
)

foreach ($relativePath in $candidateFiles) {
    $gitPath = $relativePath.Replace("\", "/")
    if ($gitPath -match $forbiddenRoots) {
        Add-Failure "Archivo privado o generado candidato a publicación: $gitPath"
        continue
    }

    $fullPath = Join-Path $projectRoot $relativePath
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
        continue
    }

    $item = Get-Item -LiteralPath $fullPath
    if ($item.Length -gt 100MB) {
        Add-Failure "Archivo mayor de 100 MiB candidato a publicación: $gitPath"
    }

    if (
        $textExtensions -notcontains $item.Extension.ToLowerInvariant() -and
        $textNamesWithoutExtension -notcontains $item.Name
    ) {
        continue
    }

    $content = Get-Content -LiteralPath $fullPath -Raw -ErrorAction Stop
    foreach ($check in $sensitivePatterns) {
        if ([regex]::IsMatch($content, $check.Pattern)) {
            Add-Failure "Posible $($check.Name) en: $gitPath"
        }
    }
}

if ($RunTests) {
    & (Join-Path $projectRoot "scripts\test.ps1")
    if ($LASTEXITCODE -ne 0) {
        Add-Failure "La suite de pruebas no aprobó."
    }
}

if ($failures.Count -gt 0) {
    Write-Host "La revisión pública encontró $($failures.Count) problema(s):" -ForegroundColor Red
    foreach ($failure in $failures) {
        Write-Host "- $failure" -ForegroundColor Red
    }
    exit 1
}

Write-Host "Revisión pública aprobada para AuralWarden $version." -ForegroundColor Green
Write-Host "$($candidateFiles.Count) archivos candidatos; no se detectaron datos privados, archivos generados ni elementos mayores de 100 MiB." -ForegroundColor Green
