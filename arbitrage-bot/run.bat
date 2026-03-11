@echo off
title ARBITRAGE NEXUS v3
echo ========================================================
echo        ARBITRAGE NEXUS v3 — REAL MARKET HUNTER
echo ========================================================
echo.

cd /d "%~dp0"

echo  [*] Auto-installing ccxt if needed...
echo  [*] Dashboard: http://localhost:8888
echo  [*] Mode: AGGRESSIVE (more trades, lower thresholds)
echo.

python server.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Python failed. Make sure Python 3.10+ is installed.
    echo Download from: https://www.python.org/downloads/
)

pause
