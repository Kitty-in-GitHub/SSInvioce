@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "API_PORT=8765"

echo Stopping API on port %API_PORT% ...
set "KILLED="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%API_PORT% .*LISTENING"') do (
  echo   taskkill PID %%P
  taskkill /F /T /PID %%P >nul 2>&1
  set "KILLED=1"
)
if defined KILLED (
  echo API stopped.
) else (
  echo No process listening on %API_PORT%.
)
