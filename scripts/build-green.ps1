# Build a portable (green) Windows folder for StarInvoiceHelper.
# Output: release/StarInvoiceHelper/  (+ optional zip)
# Requires: network (download embeddable Python + pip packages), npm for frontend.

[CmdletBinding()]
param(
    [string]$OutDir = "",
    [string]$PythonVersion = "3.12.10",
    [switch]$SkipFrontend,
    [switch]$SkipZip,
    [string]$NpmCmd = "D:\Miniconda\envs\star-invoice\npm.cmd"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $OutDir) {
    $OutDir = Join-Path $Root "release\StarInvoiceHelper"
}

$EmbedName = "python-$PythonVersion-embed-amd64"
$EmbedZip = "$EmbedName.zip"
$EmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/$EmbedZip"
$CacheDir = Join-Path $Root "release\.cache"
$Stamp = Get-Date -Format "yyyyMMdd-HHmm"

function Write-Step([string]$msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

Write-Step "Output: $OutDir"
New-Item -ItemType Directory -Force -Path $CacheDir | Out-Null
if (Test-Path $OutDir) {
    Write-Step "Cleaning previous output"
    Remove-Item -Recurse -Force $OutDir
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# --- Frontend ---
if (-not $SkipFrontend) {
    Write-Step "Building frontend"
    if (-not (Test-Path $NpmCmd)) {
        $npmProbe = Get-Command npm -ErrorAction SilentlyContinue
        if ($npmProbe) { $NpmCmd = $npmProbe.Source }
        else { throw "npm not found. Pass -NpmCmd or install Node in conda env star-invoice." }
    }
    Push-Location (Join-Path $Root "frontend")
    try {
        if (-not (Test-Path "node_modules")) {
            & $NpmCmd install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
        }
        & $NpmCmd run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    }
    finally { Pop-Location }
}

$distIndex = Join-Path $Root "frontend\dist\index.html"
if (-not (Test-Path $distIndex)) {
    throw "frontend/dist/index.html missing — build frontend first"
}

# --- Copy app files ---
Write-Step "Copying application files"
$copyMap = @(
    @{ Src = "backend"; Dst = "backend"; Recurse = $true },
    @{ Src = "frontend\dist"; Dst = "frontend\dist"; Recurse = $true },
    @{ Src = "vendor"; Dst = "vendor"; Recurse = $true },
    @{ Src = "requirements.txt"; Dst = "requirements.txt"; Recurse = $false },
    @{ Src = "pack\launcher\Start.bat"; Dst = "Start.bat"; Recurse = $false }
)
foreach ($item in $copyMap) {
    $src = Join-Path $Root $item.Src
    $dst = Join-Path $OutDir $item.Dst
    if (-not (Test-Path $src)) { throw "Missing: $src" }
    $dstParent = Split-Path $dst -Parent
    if ($dstParent) { New-Item -ItemType Directory -Force -Path $dstParent | Out-Null }
    if ($item.Recurse) {
        Copy-Item -Path $src -Destination $dst -Recurse -Force
    } else {
        Copy-Item -Path $src -Destination $dst -Force
    }
}

# Chinese alias for Start.bat (UTF-16 path via .NET)
$startBat = Join-Path $OutDir "Start.bat"
$cnBat = [System.IO.Path]::Combine($OutDir, ([string][char]0x542F) + ([string][char]0x52A8) + ".bat")
[System.IO.File]::Copy($startBat, $cnBat, $true)

# Drop bytecode / caches from copied tree
Get-ChildItem -Path $OutDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

New-Item -ItemType Directory -Force -Path (Join-Path $OutDir "data") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir "data\uploads\inbox") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir "data\exports") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir "data\cache") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutDir "data\logs") | Out-Null

@"
报销助手 · 绿色便携版
====================

使用方法
  1. 解压到任意目录（路径尽量不要有特殊权限限制）
  2. 双击「启动.bat」或「Start.bat」
  3. 浏览器打开 http://127.0.0.1:8765 （脚本会尝试自动打开）
  4. 关闭黑色命令行窗口即停止服务

说明
  - 无需安装 Python / Node
  - 数据保存在本目录 data\（数据库、上传、导出、日志）
  - OCR 模型在 vendor\ocr\models\；若删除则图片 OCR 降级，PDF 文本仍可用
  - 仅监听本机 127.0.0.1，不对外网开放

打包时间: $Stamp
Python: $PythonVersion embeddable
"@ | Set-Content -Path (Join-Path $OutDir "使用说明.txt") -Encoding UTF8

# --- Embeddable Python ---
Write-Step "Preparing embeddable Python $PythonVersion"
$zipPath = Join-Path $CacheDir $EmbedZip
if (-not (Test-Path $zipPath)) {
    Write-Host "Downloading $EmbedUrl"
    Invoke-WebRequest -Uri $EmbedUrl -OutFile $zipPath -UseBasicParsing
}
$runtime = Join-Path $OutDir "runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
Expand-Archive -Path $zipPath -DestinationPath $runtime -Force

# Enable site-packages on embeddable build
$pth = Get-ChildItem $runtime -Filter "python*._pth" | Select-Object -First 1
if (-not $pth) { throw "python*._pth not found in embeddable runtime" }
$parts = $PythonVersion.Split(".")
$pyTag = "$($parts[0])$($parts[1])"  # 3.12.10 -> 312
@"
python$pyTag.zip
.
..
Lib\site-packages
import site
"@ | Set-Content -Path $pth.FullName -Encoding ASCII

# get-pip
$getPip = Join-Path $CacheDir "get-pip.py"
if (-not (Test-Path $getPip)) {
    Write-Host "Downloading get-pip.py"
    Invoke-WebRequest -Uri "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing
}
$py = Join-Path $runtime "python.exe"
Write-Step "Installing pip into portable runtime"
& $py $getPip --no-warn-script-location
if ($LASTEXITCODE -ne 0) { throw "get-pip failed" }

Write-Step "Installing Python dependencies (this may take several minutes)"
$req = Join-Path $OutDir "requirements.txt"
& $py -m pip install --no-warn-script-location -r $req
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# Quick import check (embeddable Python reads paths from ._pth, not PYTHONPATH)
Write-Step "Smoke-checking portable runtime"
Push-Location $OutDir
try {
    & $py -c "from backend.app.main import app; from backend.app.services.ocr import ocr_available; print('app_ok', ocr_available())"
    if ($LASTEXITCODE -ne 0) { throw "portable import smoke test failed" }
}
finally { Pop-Location }

# --- Zip ---
$zipOut = Join-Path $Root "release\StarInvoiceHelper-green-$Stamp.zip"
if (-not $SkipZip) {
    Write-Step "Creating zip $zipOut"
    if (Test-Path $zipOut) { Remove-Item -Force $zipOut }
    Compress-Archive -Path $OutDir -DestinationPath $zipOut -CompressionLevel Optimal
}

Write-Host ""
Write-Host "Green pack ready:" -ForegroundColor Green
Write-Host "  Folder: $OutDir"
if (-not $SkipZip) { Write-Host "  Zip:    $zipOut" }
Write-Host "  Launch: $OutDir\Start.bat"
