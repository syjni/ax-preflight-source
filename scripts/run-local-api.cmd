@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0\.."
set "AX_PRODUCT_FROZEN_RESULTS_ROOT=artifacts\phase6_product_demo_v4\runs"
title AX Preflight API - keep open
echo AX Preflight local API is starting on http://127.0.0.1:8000
echo Keep this window open while reviewing files. Press Ctrl+C to stop.
echo.
".venv\Scripts\python.exe" -m uvicorn ax_product.api:create_local_review_app_from_env --factory --host 127.0.0.1 --port 8000
if errorlevel 1 (
  echo.
  echo [ERROR] The local API stopped unexpectedly. Review the message above.
  pause
)
