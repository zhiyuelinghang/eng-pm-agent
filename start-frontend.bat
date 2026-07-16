@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
set "FRONTEND_DIR=%ROOT%frontend"
set "URL=http://127.0.0.1:38429/"

title Eng PM Agent AI Workspace

if not exist "%FRONTEND_DIR%\package.json" (
  echo Frontend package.json not found:
  echo %FRONTEND_DIR%
  pause
  exit /b 1
)

where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo npm.cmd was not found. Please install Node.js first.
  pause
  exit /b 1
)

cd /d "%FRONTEND_DIR%"

echo Starting Eng PM Agent AI Workspace...
echo URL: %URL%
echo.
echo If the browser does not open automatically, copy the URL above.
echo Press Ctrl+C to stop the dev server.
echo.

start "" "%URL%"
npm.cmd run dev

pause
