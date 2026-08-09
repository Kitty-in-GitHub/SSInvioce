$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$condaNpm = "D:\Miniconda\envs\star-invoice\npm.cmd"
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$apiPort = 8765

if (-not (Test-Path $venvPy)) {
  Write-Host "[setup] creating .venv ..."
  python -m venv .venv
  & $venvPy -m pip install -r requirements.txt
}

if (-not (Test-Path (Join-Path $PSScriptRoot "frontend\node_modules"))) {
  Write-Host "[setup] npm install via conda env star-invoice ..."
  Push-Location frontend
  & $condaNpm install
  Pop-Location
}

Write-Host "API: http://127.0.0.1:$apiPort"
Start-Process -FilePath $venvPy -ArgumentList @(
  "-m", "uvicorn", "backend.app.main:app",
  "--host", "127.0.0.1",
  "--port", "$apiPort",
  "--log-level", "info"
)

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
& $condaNpm run dev
Pop-Location
