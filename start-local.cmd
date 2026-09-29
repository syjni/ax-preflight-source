@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ============================================================
echo  AX Preflight - local reviewer mode
echo  Secure project workspace. Your source files stay on this computer.
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python 3.12 or newer was not found on PATH.
  echo         Install Python, reopen Command Prompt, and try again.
  pause
  exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)"
if errorlevel 1 (
  echo [ERROR] Python 3.12 or newer is required.
  python --version
  pause
  exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js 20 or newer was not found on PATH.
  echo         Install Node.js, reopen Command Prompt, and try again.
  pause
  exit /b 1
)
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 20 ? 0 : 1)"
if errorlevel 1 (
  echo [ERROR] Node.js 20 or newer is required.
  node --version
  pause
  exit /b 1
)

where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm was not found on PATH. Reinstall Node.js and try again.
  pause
  exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo [ERROR] Port 8000 is already in use.
  echo         Close the previous AX Preflight API window and try again.
  pause
  exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo [ERROR] Port 5173 is already in use.
  echo         Close the previous Results Console window and try again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creating the Python environment...
  python -m venv .venv
  if errorlevel 1 goto :failed
) else (
  echo [1/4] Reusing the Python environment.
)

echo [2/4] Installing Python dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :failed

echo [3/4] Installing Results Console dependencies...
pushd results_console
call npm.cmd ci
if errorlevel 1 (
  popd
  goto :failed
)
popd

echo [4/4] Starting the local API and Results Console...
start "AX Preflight API - keep open" "%CD%\scripts\run-local-api.cmd"

echo Waiting for the local API...
powershell -NoProfile -Command "$deadline = (Get-Date).AddSeconds(20); do { try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8000/api/capabilities' -TimeoutSec 1; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 250 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
  echo [ERROR] The local API did not become ready within 20 seconds.
  echo         Review the AX Preflight API window for the cause.
  pause
  exit /b 1
)

pushd results_console
echo.
echo The browser will open at http://127.0.0.1:5173/
echo On first open, create the local administrator and default project.
echo Keep both terminal windows open while reviewing files.
echo Press Ctrl+C in both windows when finished.
echo.
call npm.cmd run dev -- --host 127.0.0.1 --port 5173 --open
popd
exit /b 0

:failed
echo.
echo [ERROR] Setup did not complete. Review the message above and try again.
pause
exit /b 1
