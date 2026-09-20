@echo off
setlocal
cd /d "%~dp0"

set "CONDA_ENV=star-invoice"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "API_PORT=8765"

rem Locate npm: NPM_CMD override, then PATH, then common conda roots
set "NPM=%NPM_CMD%"
if not defined NPM for /f "delims=" %%I in ('where npm.cmd 2^>nul') do if not defined NPM set "NPM=%%I"
if not defined NPM if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\npm.cmd" set "NPM=%CONDA_PREFIX%\npm.cmd"
if not defined NPM for %%D in ("%USERPROFILE%\miniconda3" "%USERPROFILE%\anaconda3" "%USERPROFILE%\.conda" "%LOCALAPPDATA%\miniconda3" "C:\ProgramData\miniconda3" "C:\ProgramData\anaconda3" "D:\Miniconda") do (
  if not defined NPM if exist "%%~D\envs\%CONDA_ENV%\npm.cmd" set "NPM=%%~D\envs\%CONDA_ENV%\npm.cmd"
)
if not defined NPM (
  echo [error] npm.cmd not found. Install Node.js, or run: conda env create -f environment.yml
  echo         You can also set NPM_CMD to the full path of npm.cmd.
  pause
  exit /b 1
)

if not exist "%VENV_PY%" (
  echo [setup] creating .venv ...
  python -m venv .venv
  "%VENV_PY%" -m pip install -r requirements.txt
)

if not exist "%~dp0frontend\node_modules\" (
  echo [setup] npm install via "%NPM%" ...
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
