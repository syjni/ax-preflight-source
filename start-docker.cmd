@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ============================================================
echo  AX Preflight - Docker reviewer mode
echo  Local file picker, PDF tables, Korean/English OCR included
echo ============================================================
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Desktop was not found.
  echo         Install Docker Desktop, start it, and run this file again.
  pause
  exit /b 1
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Desktop is not running.
  echo         Start Docker Desktop and run this file again.
  pause
  exit /b 1
)

echo [1/2] Building and starting AX Preflight...
docker compose up --build --detach
if errorlevel 1 goto :failed

echo [2/2] Waiting for the local service...
powershell -NoProfile -Command "$deadline = (Get-Date).AddMinutes(2); do { try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/capabilities' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo [ERROR] AX Preflight did not become ready within two minutes.
  echo         Run: docker compose logs ax-preflight
  pause
  exit /b 1
)

echo.
echo AX Preflight is ready at http://127.0.0.1:8000/
echo Use stop-docker.cmd when finished.
start "" "http://127.0.0.1:8000/"
exit /b 0

:failed
echo.
echo [ERROR] Docker setup did not complete.
echo         Run: docker compose logs ax-preflight
pause
exit /b 1
