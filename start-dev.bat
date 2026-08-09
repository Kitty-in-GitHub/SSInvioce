@echo off
setlocal
cd /d "%~dp0"

set "CONDA_ENV=star-invoice"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "NPM=D:\Miniconda\envs\%CONDA_ENV%\npm.cmd"
set "API_PORT=8765"

if not exist "%VENV_PY%" (
  echo [setup] creating .venv ...
  python -m venv .venv
  "%VENV_PY%" -m pip install -r requirements.txt
)

if not exist "%~dp0frontend\node_modules\" (
  echo [setup] npm install in conda env %CONDA_ENV% ...
  pushd frontend
  call "%NPM%" install
  popd
)

echo Starting API on http://127.0.0.1:%API_PORT%
start "StarInvoice-API" "%VENV_PY%" -m uvicorn backend.app.main:app --host 127.0.0.1 --port %API_PORT% --log-level info

echo Waiting for API health...
powershell -NoProfile -Command "for($i=0;$i -lt 30;$i++){ try { $r=Invoke-RestMethod http://127.0.0.1:%API_PORT%/api/health; if($r.service -eq 'star-invoice-helper'){ Write-Host 'API OK'; exit 0 } } catch {} Start-Sleep -Milliseconds 400 }; Write-Host 'API health check failed'; exit 1"
if errorlevel 1 (
  echo [error] API did not become ready on port %API_PORT%. See data\logs\app.log
  pause
  exit /b 1
)

echo Starting Vite on http://127.0.0.1:5173  ^(proxy /api -^> %API_PORT%^)
pushd frontend
call "%NPM%" run dev
popd
