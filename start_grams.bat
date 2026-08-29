@echo off
title Grams Launcher
cd /d "%~dp0"

echo ===================================================
echo               Starting Grams Stack
echo ===================================================
echo [1/2] Starting Docker containers (PostgreSQL & Web)...
docker compose up -d

echo [2/2] Starting grams.local mDNS Broadcaster in background...
taskkill /F /IM pythonw.exe 2>nul
start "" "C:\Python312\pythonw.exe" "%~dp0scripts\mdns_broadcaster.py"

echo.
echo ===================================================
echo    SUCCESS! Grams is active and ready.
echo.
echo    Main Phone/Wi-Fi URL:  http://grams.local
echo    Direct PC Browser URL: http://localhost
echo ===================================================
echo.
timeout /t 5
