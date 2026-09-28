@echo off
setlocal EnableExtensions
cd /d "%~dp0"
docker compose down
if errorlevel 1 (
  echo [ERROR] AX Preflight Docker service could not be stopped.
  pause
  exit /b 1
)
echo AX Preflight Docker service stopped. Local review data is preserved.
