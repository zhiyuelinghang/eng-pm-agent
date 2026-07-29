@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "ROOT=%~dp0"
set "FRONTEND_DIST=%ROOT%frontend\dist"
set "BACKEND_DIR=%ROOT%backend"
set "WEB_GATEWAY=%ROOT%scripts\dobby_web_gateway.py"
set "PYTHON_EXE=%ROOT%python-3.13.14\python.exe"

title Dobby 服务器工程管理平台

if not exist "%FRONTEND_DIST%\index.html" (
    echo [错误] 缺少预构建平台前端：%FRONTEND_DIST%\index.html
    pause
    exit /b 1
)

if not exist "%BACKEND_DIR%\app\main.py" (
    echo [错误] 缺少平台后端：%BACKEND_DIR%\app\main.py
    pause
    exit /b 1
)

if not exist "%WEB_GATEWAY%" (
    echo [错误] 缺少 Python Web 网关：%WEB_GATEWAY%
    pause
    exit /b 1
)

if not exist "%PYTHON_EXE%" (
    echo [错误] 缺少项目便携 Python：%PYTHON_EXE%
    pause
    exit /b 1
)

call :STOP_PORT 38430 "平台后端"
call :STOP_PORT 38429 "平台前端"

echo [平台] 正在启动后端：http://127.0.0.1:38430
start "Dobby Platform API" /b "%PYTHON_EXE%" -m uvicorn app.main:app --app-dir "%BACKEND_DIR%" --host 127.0.0.1 --port 38430

call :WAIT_PORT 38430 30 "平台后端"
if errorlevel 1 (
    echo [错误] 平台后端启动超时。
    pause
    exit /b 1
)

echo [平台] 正在启动预构建页面：http://0.0.0.0:38429
echo [平台] 服务器无需 Node.js、npm 或 pnpm。
    echo [平台] 关闭本窗口会停止平台前端；完整停止请运行 一键停止全部服务.bat。
"%PYTHON_EXE%" "%WEB_GATEWAY%" --mode platform
exit /b %ERRORLEVEL%

:STOP_PORT
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do (
    if not "%%P"=="0" (
        echo [平台] 端口 %~1 被 PID=%%P 占用，正在关闭 %~2……
        taskkill /F /T /PID %%P >nul 2>nul
    )
)
exit /b 0

:WAIT_PORT
set "WAIT_PORT_NUMBER=%~1"
set "WAIT_LIMIT=%~2"
set "WAIT_NAME=%~3"
set "WAIT_COUNT=0"

:WAIT_PORT_LOOP
netstat -ano | findstr /R /C:":%WAIT_PORT_NUMBER% .*LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [就绪] %WAIT_NAME% 已监听端口 %WAIT_PORT_NUMBER%。
    exit /b 0
)
set /a WAIT_COUNT+=1 >nul
if %WAIT_COUNT% GEQ %WAIT_LIMIT% exit /b 1
ping 127.0.0.1 -n 2 >nul
goto WAIT_PORT_LOOP
