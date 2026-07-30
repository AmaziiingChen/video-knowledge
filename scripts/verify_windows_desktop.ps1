[CmdletBinding()]
param(
    [switch]$SkipInstall,
    [switch]$SkipPackage
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not $SkipInstall) {
    python -m pip install -r requirements.txt
    Push-Location frontend
    npm ci
    Pop-Location
}

# These tests cover the platform-neutral library, queue, search and filesystem
# contracts, plus the Windows clipboard command selection. They intentionally
# avoid source fixtures and credentials that are not part of a release image.
python -m pytest tests/test_core.py -q

Push-Location frontend
npm run build
if (-not $SkipPackage) {
    npm run desktop:package:win
    $installer = Get-ChildItem -Path dist -Filter "KnowledgeHub-*-win-x64.exe" | Select-Object -First 1
    if ($null -eq $installer) {
        throw "未找到 NSIS 安装包；请检查 electron-builder 输出。"
    }
    Write-Host "已生成安装包：$($installer.FullName)"
}
Pop-Location
