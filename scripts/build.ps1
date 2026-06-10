param(
    [switch]$SkipClean
)

$ErrorActionPreference = "Stop"

Push-Location (Join-Path $PSScriptRoot "..")
try {
    python -m py_compile src/variable_monitor_v3.py tools/lan_scanner.py

    @'
import json
from pathlib import Path

with Path("src/config.json").open("r", encoding="utf-8") as f:
    json.load(f)
print("config.json ok")
'@ | python -

    $cleanFlag = @()
    if (-not $SkipClean) {
        $cleanFlag = @("--clean")
    }

    pyinstaller --noconfirm @cleanFlag "packaging\variable_monitor_v3.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed for variable_monitor_v3.spec"
    }

    pyinstaller --noconfirm @cleanFlag "packaging\lan_scanner.spec"
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed for lan_scanner.spec"
    }

    $releaseName = "genesis-udp-video-debug-assistant-windows"
    $releaseDir = Join-Path (Get-Location) "dist\$releaseName"
    $releaseZip = Join-Path (Get-Location) "dist\$releaseName.zip"

    if (Test-Path -LiteralPath $releaseDir) {
        Remove-Item -LiteralPath $releaseDir -Recurse -Force
    }
    if (Test-Path -LiteralPath $releaseZip) {
        Remove-Item -LiteralPath $releaseZip -Force
    }

    New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null
    Copy-Item -LiteralPath "dist\genesis-udp-video-debug-assistant.exe" -Destination $releaseDir
    Copy-Item -LiteralPath "dist\lan-scanner.exe" -Destination $releaseDir
    Copy-Item -LiteralPath "src\config.json" -Destination $releaseDir
    Copy-Item -LiteralPath "docs\README.md" -Destination $releaseDir
    Copy-Item -LiteralPath "docs\LICENSE" -Destination $releaseDir

    Compress-Archive -Path (Join-Path $releaseDir "*") -DestinationPath $releaseZip -Force

    Write-Host ""
    Write-Host "Build complete. Release files:"
    Get-Item -LiteralPath $releaseZip | Select-Object Name, Length, LastWriteTime
    Get-ChildItem $releaseDir | Select-Object Name, Length, LastWriteTime
}
finally {
    Pop-Location
}
