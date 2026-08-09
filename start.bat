@echo off
setlocal
cd /d "%~dp0"

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
set "NPM=D:\Miniconda\envs\star-invoice\npm.cmd"
set "API_PORT=8765"

if not exist "%VENV_PY%" (
  echo [setup] creating .venv ...
  python -m venv .venv
  "%VENV_PY%" -m pip install -r requirements.txt
)

if not exist "%~dp0frontend\dist\index.html" (
  echo [build] building frontend ...
  pushd frontend
  if not exist node_modules call "%NPM%" install
  call "%NPM%" run build
  popd
)

echo Open http://127.0.0.1:%API_PORT%
"%VENV_PY%" -m uvicorn backend.app.main:app --host 127.0.0.1 --port %API_PORT% --log-level info
