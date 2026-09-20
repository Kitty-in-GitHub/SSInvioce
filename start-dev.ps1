$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$condaEnv = "star-invoice"
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$apiPort = 8765

# Locate npm: NPM_CMD override, then PATH, then common conda roots
function Resolve-NpmCmd {
    param([string]$EnvName)
    if ($env:NPM_CMD) {
        if (Test-Path $env:NPM_CMD) { return $env:NPM_CMD }
        throw "NPM_CMD points to a missing file: $env:NPM_CMD"
    }
    $onPath = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $onPath) { $onPath = Get-Command npm -ErrorAction SilentlyContinue }
    if ($onPath) { return $onPath.Source }
    if ($env:CONDA_PREFIX) {
        $candidate = Join-Path $env:CONDA_PREFIX "npm.cmd"
        if (Test-Path $candidate) { return $candidate }
    }
    $roots = @(
        (Join-Path $env:USERPROFILE "miniconda3"),
        (Join-Path $env:USERPROFILE "anaconda3"),
        (Join-Path $env:USERPROFILE ".conda"),
        (Join-Path $env:LOCALAPPDATA "miniconda3"),
        "C:\ProgramData\miniconda3",
        "C:\ProgramData\anaconda3",
        "D:\Miniconda"
    )
    foreach ($root in $roots) {
        $candidate = Join-Path $root "envs\$EnvName\npm.cmd"
        if (Test-Path $candidate) { return $candidate }
    }
    throw "npm.cmd not found. Install Node.js, or run: conda env create -f environment.yml (or set NPM_CMD)."
}

$npmCmd = Resolve-NpmCmd -EnvName $condaEnv

if (-not (Test-Path $venvPy)) {
  Write-Host "[setup] creating .venv ..."
  python -m venv .venv
  & $venvPy -m pip install -r requirements.txt
}

if (-not (Test-Path (Join-Path $PSScriptRoot "frontend\node_modules"))) {
  Write-Host "[setup] npm install via $npmCmd ..."
  Push-Location frontend
  & $npmCmd install
  Pop-Location
}

Write-Host "API: http://127.0.0.1:$apiPort"
Write-Host "Close the StarInvoice-API window to stop, or run stop-dev.bat if it will not close."
$stopBat = Join-Path $PSScriptRoot "stop-dev.bat"
if (Test-Path $stopBat) { & $stopBat }
Start-Process -FilePath "cmd.exe" -ArgumentList @(
  "/c",
  "`"$venvPy`" -m uvicorn backend.app.main:app --host 127.0.0.1 --port $apiPort --reload --reload-dir backend --log-level info --no-use-colors"
) -WorkingDirectory $PSScriptRoot -WindowStyle Normal

$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    $r = Invoke-RestMethod "http://127.0.0.1:$apiPort/api/health"
    if ($r.service -eq "star-invoice-helper") {
      Write-Host "API OK"
      $ok = $true
      break
    }
  } catch {}
  Start-Sleep -Milliseconds 400
}
if (-not $ok) {
  throw "API health check failed on port $apiPort. See data/logs/app.log"
}

Push-Location frontend
& $npmCmd run dev
Pop-Location
