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

call "%~dp0stop-dev.bat"

echo Starting API on http://127.0.0.1:%API_PORT%
echo Close the "StarInvoice-API" window to stop, or run stop-dev.bat if it will not close.
start "StarInvoice-API" cmd /c ""%VENV_PY%" -m uvicorn backend.app.main:app --host 127.0.0.1 --port %API_PORT% --reload --reload-dir backend --log-level info --no-use-colors"

echo Waiting for API health...
set "HEALTH_OK="
for /L %%i in (1,1,30) do (
  if not defined HEALTH_OK (
    "%VENV_PY%" -c "import json,urllib.request,sys; d=json.loads(urllib.request.urlopen('http://127.0.0.1:%API_PORT%/api/health', timeout=1).read().decode()); sys.exit(0 if d.get('service')=='star-invoice-helper' else 1)" 2>nul
    if not errorlevel 1 (
      echo API OK
      set "HEALTH_OK=1"
    ) else (
      "%VENV_PY%" -c "import time; time.sleep(0.4)"
    )
  )
)
if not defined HEALTH_OK (
  echo [error] API did not become ready on port %API_PORT%. See data\logs\app.log
  pause
  exit /b 1
)

echo Starting Vite on http://127.0.0.1:5180  ^(proxy /api -^> %API_PORT%^)
pushd frontend
call "%NPM%" run dev
popd
