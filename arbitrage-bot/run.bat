@echo off
title ARBITRAGE NEXUS v4
echo ========================================================
echo        ARBITRAGE NEXUS v4 — LIVE EXECUTION ENGINE
echo ========================================================
echo.

cd /d "%~dp0"

echo  [*] Auto-installing ccxt if needed...
echo  [*] Dashboard: http://localhost:8888
echo  [*] Kill Switch: http://localhost:8888/api/kill
echo.

python server.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Python failed. Make sure Python 3.10+ is installed.
    echo Download from: https://www.python.org/downloads/
)

pause
