@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-deskdrop.ps1"
if errorlevel 1 (
  echo.
  echo DeskDrop stopped because of an error.
  pause
)
