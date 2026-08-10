@echo off
echo ========================================
echo   Dobby - Launch All Services
echo ========================================
echo:
echo [1/2] Starting Embed Server on port 9999...
start "" "%~dp0start_embed.bat"

echo   Waiting 20 seconds for model to load...
ping -n 21 127.0.0.1 > nul

echo [2/2] Starting Web UI on port 7860...
start "" "%~dp0start_web.bat"

echo:
echo ========================================
echo   Both services launched!
echo   Web: http://localhost:7860
echo ========================================
echo:
echo Close the two terminal windows to stop.
pause
