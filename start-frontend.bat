@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
set "FRONTEND_DIR=%ROOT%frontend"
set "BACKEND_DIR=%ROOT%backend"
set "PYTHON_EXE=D:\ProgramData\anaconda3\python.exe"
set "URL=http://127.0.0.1:38429/"
set "API_URL=http://127.0.0.1:8000/health"

title Eng PM Agent AI Workspace

if not exist "%FRONTEND_DIR%\package.json" (
  echo Frontend package.json not found:
  echo %FRONTEND_DIR%
  pause
  exit /b 1
)

if not exist "%BACKEND_DIR%\app\main.py" (
  echo Backend entrypoint was not found:
  echo %BACKEND_DIR%\app\main.py
  pause
  exit /b 1
)

if not exist "%PYTHON_EXE%" (
  echo Anaconda Python was not found:
  echo %PYTHON_EXE%
  pause
  exit /b 1
)

where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo npm.cmd was not found. Please install Node.js first.
  pause
  exit /b 1
)

echo Starting Eng PM Agent AI Workspace...
echo API: %API_URL%
echo Web: %URL%
echo.

netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul
if errorlevel 1 (
  echo Starting backend API on port 8000...
  start "Eng PM Agent API" /b "%PYTHON_EXE%" -m uvicorn app.main:app --app-dir "%BACKEND_DIR%" --host 127.0.0.1 --port 8000
) else (
  echo Backend API is already running on port 8000.
)

set /a RETRIES=0
:WAIT_API
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -Uri '%API_URL%' -TimeoutSec 1).StatusCode -eq 200 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 goto API_READY
set /a RETRIES+=1
if %RETRIES% GEQ 15 goto API_TIMEOUT
timeout /t 1 /nobreak >nul
goto WAIT_API

:API_READY
echo Backend API is ready.
goto START_FRONTEND

:API_TIMEOUT
echo Backend API did not become ready within 15 seconds. Check its console window before logging in.

:START_FRONTEND
netstat -ano | findstr /r /c:":38429 .*LISTENING" >nul
if not errorlevel 1 (
  echo Frontend is already running on port 38429.
  start "" "%URL%"
  pause
  exit /b 0
)

start "" "%URL%"
cd /d "%FRONTEND_DIR%"
echo Starting frontend development server on port 38429...
echo Press Ctrl+C to stop the frontend server.
npm.cmd run dev

pause
