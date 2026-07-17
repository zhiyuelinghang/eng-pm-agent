@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
set "FRONTEND_DIR=%ROOT%frontend"
set "BACKEND_DIR=%ROOT%backend"
set "PYTHON_EXE=D:\ProgramData\anaconda3\python.exe"
set "URL=http://127.0.0.1:38429/"
set "API_URL=http://127.0.0.1:38430/health"

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

call :STOP_PORT 38430 "backend API"
call :STOP_PORT 38429 "frontend development server"

echo Starting backend API on port 38430...
echo Backend logs will be shown in this window.
start "Eng PM Agent API" /b "%PYTHON_EXE%" -m uvicorn app.main:app --app-dir "%BACKEND_DIR%" --host 127.0.0.1 --port 38430

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
echo Backend API did not become ready within 15 seconds. Check the logs in this window before logging in.

:START_FRONTEND
start "" "%URL%"
cd /d "%FRONTEND_DIR%"
echo Starting frontend development server on port 38429...
echo Keep this window open to view frontend and API logs.
echo Press Ctrl+C to stop the services, or close this window to terminate them.
echo.
call npm.cmd run dev

set "FRONTEND_EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%FRONTEND_EXIT_CODE%"=="0" (
  echo Frontend service exited with code %FRONTEND_EXIT_CODE%.
) else (
  echo Frontend service has stopped.
)
echo Press any key to close this window.
pause
exit /b %FRONTEND_EXIT_CODE%

:STOP_PORT
set "PORT=%~1"
set "SERVICE_NAME=%~2"
set "PORT_PID="

for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do (
  set "PORT_PID=%%P"
  echo Port %PORT% is occupied by process %%P. Stopping %SERVICE_NAME%...
  taskkill /PID %%P /T /F >nul 2>nul
)

if defined PORT_PID (
  timeout /t 1 /nobreak >nul
) else (
  echo Port %PORT% is available.
)
exit /b 0
