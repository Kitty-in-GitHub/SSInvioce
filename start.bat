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

if not exist "%VENV_PY%" (
  echo [setup] creating .venv ...
  python -m venv .venv
  "%VENV_PY%" -m pip install -r requirements.txt
)

if not exist "%~dp0frontend\dist\index.html" (
  if not defined NPM (
    echo [error] npm.cmd not found. Install Node.js, or run: conda env create -f environment.yml
    echo         You can also set NPM_CMD to the full path of npm.cmd.
    pause
    exit /b 1
  )
  echo [build] building frontend ...
  pushd frontend
  if not exist node_modules call "%NPM%" install
  call "%NPM%" run build
  popd
  if not exist "%~dp0frontend\dist\index.html" (
    echo [error] frontend build failed - frontend\dist\index.html not found. See output above.
    pause
    exit /b 1
  )
)

echo Open http://127.0.0.1:%API_PORT%
"%VENV_PY%" -m uvicorn backend.app.main:app --host 127.0.0.1 --port %API_PORT% --log-level info --no-use-colors
