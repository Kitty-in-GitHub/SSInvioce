@echo off
setlocal
cd /d "%~dp0"
echo Building green portable pack...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\build-green.ps1" %*
if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)
echo.
echo Done. See release\StarInvoiceHelper\
pause
