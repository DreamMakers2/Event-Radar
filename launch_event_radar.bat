@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%start_event_radar.ps1"

if not exist "%PS1%" (
  echo start_event_radar.ps1 not found:
  echo   %PS1%
  echo.
  pause
  exit /b 1
)

cls
echo Starting Event Radar...
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo.
  echo Event Radar exited with code %EXIT_CODE%.
  echo.
  pause
)

exit /b %EXIT_CODE%
