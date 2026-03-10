@echo off
echo ========================================================
echo        ARBITRAGE NEXUS - Starting...
echo ========================================================
echo.

cd /d "%~dp0"

echo  Dashboard will open at: http://localhost:8888
echo.

python server.py

pause
