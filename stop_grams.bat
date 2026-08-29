@echo off
title Grams Stopper
cd /d "%~dp0"

echo Stopping Grams containers and mDNS Broadcaster...
taskkill /F /IM pythonw.exe 2>nul
docker compose down

echo Grams stopped successfully.
timeout /t 3
