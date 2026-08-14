@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "ROOT=%~dp0"
set "PY=%ROOT%runtime\python.exe"
set "API_HOST=127.0.0.1"
set "API_PORT=8765"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"

if not exist "%PY%" (
  echo [ERROR] runtime\python.exe missing. Pack is incomplete.
  pause
  exit /b 1
)

if not exist "%ROOT%frontend\dist\index.html" (
  echo [ERROR] frontend\dist missing. Rebuild the green pack.
  pause
  exit /b 1
)

if not exist "%ROOT%data" mkdir "%ROOT%data"

echo.
echo  Star Invoice Helper ^(portable^)
echo  Open: http://%API_HOST%:%API_PORT%
echo  Close this window to stop.
echo.

start "" "http://%API_HOST%:%API_PORT%"
"%PY%" -m uvicorn backend.app.main:app --host %API_HOST% --port %API_PORT% --log-level info --no-use-colors
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
  echo.
  echo [ERROR] Server exited with code %EC%
  pause
)
exit /b %EC%
