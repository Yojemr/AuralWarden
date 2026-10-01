param(
    [switch]$WithCapture,
    [switch]$WithStt,
    [switch]$WithCuda,
    [switch]$WithDiarization,
    [switch]$WithUi,
    [switch]$BundleFfmpeg,
    [switch]$VersionedFolder,
    [switch]$PreservePreviousVersions,
    [ValidateRange(0, 20)]
    [int]$PreviousVersionsToKeep = 2
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

# Do not let unrelated native DLL directories inherited from the Codex runtime
# override the Visual C++ runtime selected for the portable application.
$pathSeparator = [System.IO.Path]::PathSeparator
$env:PATH = (($env:PATH -split $pathSeparator) | Where-Object {
    $_ -notmatch '[\\/]codex-runtimes[\\/].*[\\/]dependencies[\\/]native[\\/]'
}) -join $pathSeparator

if (-not (Test-Path $venvPython)) {
    throw "Run scripts\setup.ps1 first."
}
function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) { throw "$Step failed (exit $LASTEXITCODE)." }
}

& $venvPython -c "import PyInstaller, auralwarden"
Assert-NativeSuccess "Builder import"
if ($WithCapture) {
    & $venvPython -c "import streamlink, yt_dlp, pyaudiowpatch, pycaw, comtypes"
    Assert-NativeSuccess "Capture imports"
}
if ($WithStt) {
    & $venvPython -c "import faster_whisper, ctranslate2"
    Assert-NativeSuccess "Transcription imports"
}
if ($WithCuda) {
    if (-not $WithStt) {
        throw "-WithCuda requires -WithStt."
    }
    & $venvPython -c "import nvidia.cublas"
    Assert-NativeSuccess "CUDA imports"
}
if ($WithDiarization) {
    & $venvPython -c "import sherpa_onnx"
    Assert-NativeSuccess "Diarization imports"
}
if ($WithUi) {
    & $venvPython -c "import PySide6, qtawesome"
    Assert-NativeSuccess "UI imports"
}

$appName = if ($WithUi) { "AuralWarden" } else { "AuralWarden-Backend" }
$version = (Get-Content (Join-Path $projectRoot "VERSION") -Raw).Trim()
$sourceVersion = (& $venvPython -c "import auralwarden; print(auralwarden.__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or $sourceVersion -ne $version) {
    throw "VERSION and the application version do not match."
}
$installedVersion = (& $venvPython -c "import importlib.metadata; print(importlib.metadata.version('auralwarden'))").Trim()
if ($LASTEXITCODE -ne 0 -or $installedVersion -ne $version) {
    throw "Installed package metadata does not match VERSION; refresh the editable installation."
}
$bundleName = if ($VersionedFolder) { "$appName-$version" } else { $appName }
$distRoot = if ($VersionedFolder) {
    Join-Path $projectRoot "outputs"
} else {
    Join-Path $projectRoot "dist"
}
$packageRoot = Join-Path $distRoot $bundleName
if ($VersionedFolder -and (Test-Path $packageRoot)) {
    throw "The release folder already exists: $packageRoot"
}
$entryPoint = if ($WithUi) {
    "$projectRoot\src\auralwarden\gui_main.py"
} else {
    "$projectRoot\src\auralwarden\__main__.py"
}
$windowMode = if ($WithUi) { "--windowed" } else { "--console" }
$arguments = @(
    "--noconfirm",
    "--clean",
    "--distpath", $distRoot,
    "--contents-directory", "runtime",
    $windowMode,
    "--name", $bundleName,
    "--copy-metadata", "auralwarden",
    $entryPoint
)
$modelCatalog = Join-Path $projectRoot "src\auralwarden\model_downloads.json"
$arguments = @("--add-data", "$modelCatalog;auralwarden") + $arguments
if ($WithCapture) {
    $arguments = @(
        "--collect-all", "streamlink",
        "--collect-all", "yt_dlp",
        "--hidden-import", "pyaudiowpatch",
        "--hidden-import", "pycaw.pycaw",
        "--hidden-import", "comtypes.client"
    ) + $arguments
}
if ($WithStt) {
    $arguments = @("--collect-all", "faster_whisper", "--collect-all", "ctranslate2") + $arguments
}
if ($WithCuda) {
    $nvidiaRoot = Join-Path $projectRoot ".venv\Lib\site-packages\nvidia"
    foreach ($component in @("cublas")) {
        $source = Join-Path $nvidiaRoot "$component\bin"
        if (Test-Path $source) {
            $destination = "nvidia\$component\bin"
            $arguments = @("--add-binary", "$source;$destination") + $arguments
        }
    }
}
if ($WithDiarization) {
    $arguments = @("--collect-all", "sherpa_onnx") + $arguments
}
if ($WithUi) {
    $assets = "$projectRoot\src\auralwarden\ui\assets"
    $icon = Join-Path $assets "app-icon.ico"
    $arguments = @(
        "--add-data", "$assets;auralwarden\ui\assets",
        "--icon", $icon
    ) + $arguments
}
if ($BundleFfmpeg) {
    $ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if (-not $ffmpeg) {
        throw "FFmpeg was requested for the portable package but was not found."
    }
    $arguments = @("--add-binary", "$($ffmpeg.Source);.") + $arguments
}
& $venvPython -m PyInstaller @arguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed; previous portable versions were preserved."
}

# Qt 6 on current Windows versions uses the ICU implementation provided by
# System32. PyInstaller can mistakenly copy Poppler's ICU DLLs from the Codex
# runtime into the package root; those files shadow the Windows DLL and make
# PySide6.QtCore fail with "The specified procedure could not be found".
if ($WithUi) {
    $contentsRoot = Join-Path $packageRoot "runtime"
    $conflictingIcuFiles = @(
        (Join-Path $contentsRoot "icuuc.dll"),
        (Join-Path $contentsRoot "icuin.dll")
    )
    $conflictingIcuFiles += Get-ChildItem -LiteralPath $contentsRoot -File -Filter "icudt*.dll" -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName
    $resolvedPackageRoot = [System.IO.Path]::GetFullPath($packageRoot).TrimEnd('\') + '\'
    foreach ($conflictingIcuFile in $conflictingIcuFiles | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $conflictingIcuFile -PathType Leaf)) {
            continue
        }
        $resolvedIcuFile = [System.IO.Path]::GetFullPath($conflictingIcuFile)
        if (-not $resolvedIcuFile.StartsWith($resolvedPackageRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove an ICU DLL outside the portable package."
        }
        Remove-Item -LiteralPath $resolvedIcuFile -Force
        Write-Host "Removed conflicting ICU runtime $resolvedIcuFile."
    }
    $unusedNvblas = Join-Path $contentsRoot "nvidia\cublas\bin\nvblas64_12.dll"
    if (Test-Path -LiteralPath $unusedNvblas -PathType Leaf) {
        Remove-Item -LiteralPath $unusedNvblas -Force
        Write-Host "Removed unused NVBLAS compatibility library $unusedNvblas."
    }
    $bundledCudnnLoader = Join-Path $contentsRoot "ctranslate2\cudnn64_9.dll"
    if ($WithCuda) {
        if (-not (Test-Path -LiteralPath $bundledCudnnLoader -PathType Leaf)) {
            throw "CTranslate2 did not provide its required cuDNN loader: $bundledCudnnLoader"
        }
        $redundantCudnnPackage = Join-Path $contentsRoot "nvidia\cudnn"
        if (Test-Path -LiteralPath $redundantCudnnPackage -PathType Container) {
            $resolvedCudnnPackage = [System.IO.Path]::GetFullPath($redundantCudnnPackage)
            if (-not $resolvedCudnnPackage.StartsWith($resolvedPackageRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to remove cuDNN outside the portable package."
            }
            Remove-Item -LiteralPath $redundantCudnnPackage -Recurse -Force
            Write-Host "Removed the redundant cuDNN package; CTranslate2 includes its required loader."
        }
    } elseif (Test-Path -LiteralPath $bundledCudnnLoader -PathType Leaf) {
        Remove-Item -LiteralPath $bundledCudnnLoader -Force
        Write-Host "Removed the optional cuDNN loader from the CPU portable."
    }
}

$generatedExecutable = Join-Path $packageRoot "$bundleName.exe"
# Editable-install origins are build-machine metadata, not portable runtime data.
$resolvedRuntimeRoot = [System.IO.Path]::GetFullPath((Join-Path $packageRoot "runtime")).TrimEnd('\') + '\'
Get-ChildItem -LiteralPath (Join-Path $packageRoot "runtime") -Directory -Filter "*.dist-info" | ForEach-Object {
    $originFile = Join-Path $_.FullName "direct_url.json"
    if (Test-Path -LiteralPath $originFile -PathType Leaf) {
        $resolvedOrigin = [System.IO.Path]::GetFullPath($originFile)
        if (-not $resolvedOrigin.StartsWith($resolvedRuntimeRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove install-origin metadata outside the portable runtime."
        }
        Remove-Item -LiteralPath $resolvedOrigin -Force
    }
}
if ($VersionedFolder -and (Test-Path $generatedExecutable)) {
    Move-Item -LiteralPath $generatedExecutable -Destination (Join-Path $packageRoot "$appName.exe")
}
$portableFlag = Join-Path $packageRoot "portable.flag"
New-Item -ItemType File -Force -Path $portableFlag | Out-Null
try {
    (Get-Item -LiteralPath $portableFlag).Attributes = [System.IO.FileAttributes]::Hidden
} catch {
    Write-Warning "The portable marker could not be hidden: $($_.Exception.Message)"
}
$packageDocs = Join-Path $packageRoot "docs"
New-Item -ItemType Directory -Force -Path $packageDocs | Out-Null
foreach ($publicFile in @("README.md", "CHANGELOG.md", "LICENSE", "NOTICE", "SECURITY.md", "CONTRIBUTING.md")) {
    Copy-Item (Join-Path $projectRoot $publicFile) $packageRoot -Force
}
if ($WithUi) {
    # The portable package only includes reader-facing documentation referenced
    # by its README. Historical validation notes and UI specifications remain
    # in the source repository.
    foreach ($publicDoc in @(
        "AGENT_CONTROL.md",
        "ARCHITECTURE.md",
        "BACKEND.md",
        "FIRST_RUN.md",
        "GITHUB_PUBLISHING.md",
        "GUI.md",
        "HARDWARE.md",
        "PRIVACY.md",
        "RELEASE_CHECKLIST.md",
        "RELEASE_NOTES_$version.md",
        "ROADMAP.md",
        "THIRD_PARTY_NOTICES.md",
        "agent-control-request.example.json",
        "agent-control.schema.json"
    )) {
        Copy-Item (Join-Path $projectRoot "docs\$publicDoc") $packageDocs -Force
    }
    Copy-Item (Join-Path $projectRoot "docs\assets") $packageDocs -Recurse -Force
    Copy-Item (Join-Path $projectRoot "scripts\AuralWarden-Control.ps1") $packageRoot -Force
}

# Preserve notices from every bundled Python distribution. This inventory is
# generated from the exact build environment and contains no user data.
$licenseRoot = Join-Path $packageDocs "licenses"
New-Item -ItemType Directory -Force -Path $licenseRoot | Out-Null
& $venvPython (Join-Path $projectRoot "scripts\collect-licenses.py") --output $licenseRoot --profile $(if ($WithCuda) { "cuda" } else { "cpu" })
if ($LASTEXITCODE -ne 0) {
    throw "Third-party license collection failed."
}
if ($BundleFfmpeg) {
    $ffmpegRoot = Split-Path -Parent (Split-Path -Parent $ffmpeg.Source)
    foreach ($ffmpegNotice in @("LICENSE", "README.txt")) {
        $candidate = Join-Path $ffmpegRoot $ffmpegNotice
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            Copy-Item $candidate (Join-Path $licenseRoot "FFmpeg-$ffmpegNotice") -Force
        } else {
            throw "Required FFmpeg notice missing: $candidate"
        }
    }
    & $ffmpeg.Source -version | Out-File (Join-Path $licenseRoot "FFmpeg-build.txt") -Encoding utf8
    Assert-NativeSuccess "FFmpeg build identification"
}

$finalExecutable = Join-Path $packageRoot "$appName.exe"
if (-not (Test-Path -LiteralPath $finalExecutable -PathType Leaf)) {
    throw "The portable executable was not created: $finalExecutable"
}

if ($VersionedFolder -and -not $PreservePreviousVersions) {
    $versionPattern = "^$([regex]::Escape($appName))-(\d+\.\d+\.\d+)$"
    $versionedPackages = Get-ChildItem -LiteralPath $distRoot -Directory | ForEach-Object {
        if ($_.Name -match $versionPattern) {
            [pscustomobject]@{
                Directory = $_
                Version = [version]$Matches[1]
            }
        }
    } | Sort-Object Version -Descending
    $obsoletePackages = $versionedPackages | Select-Object -Skip (1 + $PreviousVersionsToKeep)
    $resolvedDistRoot = [System.IO.Path]::GetFullPath($distRoot).TrimEnd('\') + '\'
    foreach ($obsolete in $obsoletePackages) {
        $target = [System.IO.Path]::GetFullPath($obsolete.Directory.FullName)
        if (-not $target.StartsWith($resolvedDistRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove a package outside outputs: $target"
        }
        if ($target -eq [System.IO.Path]::GetFullPath($packageRoot)) {
            continue
        }
        $oldExe = Join-Path $target "$appName.exe"
        $active = @(Get-Process -Name $appName -ErrorAction SilentlyContinue | Where-Object {
            try {
                -not $_.Path -or [System.IO.Path]::GetFullPath($_.Path) -eq [System.IO.Path]::GetFullPath($oldExe)
            } catch {
                $true
            }
        })
        $privateData = Join-Path $target "data"
        if ($active -or (Test-Path -LiteralPath $privateData)) {
            Write-Host "Preserved $target because it is active or contains local data."
            continue
        }
        Remove-Item -LiteralPath $target -Recurse -Force
        Write-Host "Removed obsolete portable package $target."
    }
}

$buildTarget = Join-Path $projectRoot "build\$bundleName"
if (Test-Path -LiteralPath $buildTarget -PathType Container) {
    $resolvedBuildRoot = [System.IO.Path]::GetFullPath((Join-Path $projectRoot "build")).TrimEnd('\') + '\'
    $resolvedBuildTarget = [System.IO.Path]::GetFullPath($buildTarget)
    if (-not $resolvedBuildTarget.StartsWith($resolvedBuildRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a build folder outside the project build directory."
    }
    Remove-Item -LiteralPath $resolvedBuildTarget -Recurse -Force
}
$specPath = Join-Path $projectRoot "$bundleName.spec"
if (Test-Path -LiteralPath $specPath -PathType Leaf) {
    Remove-Item -LiteralPath $specPath -Force
}
Write-Host "Portable package created under $packageRoot."
