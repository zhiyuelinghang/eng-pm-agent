param(
    [string]$Version = "6.8.1"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$targetDir = Join-Path $projectRoot "runtime\centrifugo"
$targetExe = Join-Path $targetDir "centrifugo.exe"
$archiveName = "centrifugo_${Version}_windows_amd64.zip"
$releaseBase = "https://github.com/centrifugal/centrifugo/releases/download/v${Version}"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("dobby-centrifugo-" + [Guid]::NewGuid().ToString("N"))
$resolvedTempRoot = [System.IO.Path]::GetFullPath($tempRoot)
$systemTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())

if (-not $resolvedTempRoot.StartsWith($systemTempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The temporary directory is outside the system temp root."
}

New-Item -ItemType Directory -Path $tempRoot | Out-Null
try {
    $archivePath = Join-Path $tempRoot $archiveName
    $checksumsPath = Join-Path $tempRoot "centrifugo_${Version}_checksums.txt"
    Invoke-WebRequest -Uri "$releaseBase/$archiveName" -OutFile $archivePath
    Invoke-WebRequest -Uri "$releaseBase/centrifugo_${Version}_checksums.txt" -OutFile $checksumsPath

    $checksumLine = Select-String -LiteralPath $checksumsPath -Pattern ([regex]::Escape($archiveName)) | Select-Object -First 1
    if (-not $checksumLine) {
        throw "The official checksum file does not contain $archiveName."
    }
    $expectedHash = ($checksumLine.Line.Trim() -split "\s+")[0].ToLowerInvariant()
    $actualHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($expectedHash -ne $actualHash) {
        throw "The Centrifugo archive SHA256 checksum does not match."
    }

    $extractDir = Join-Path $tempRoot "extract"
    Expand-Archive -LiteralPath $archivePath -DestinationPath $extractDir
    $sourceExe = Get-ChildItem -LiteralPath $extractDir -Filter "centrifugo.exe" -Recurse | Select-Object -First 1
    if (-not $sourceExe) {
        throw "centrifugo.exe was not found in the official archive."
    }
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    Copy-Item -LiteralPath $sourceExe.FullName -Destination $targetExe -Force
    Write-Host "[Done] Centrifugo $Version installed at $targetExe"
}
finally {
    if (Test-Path -LiteralPath $tempRoot) {
        $checkedTarget = [System.IO.Path]::GetFullPath($tempRoot)
        if ($checkedTarget.StartsWith($systemTempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $tempRoot -Recurse -Force
        }
    }
}
