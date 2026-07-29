@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "AGENTSCOPE_PORT=18642"
set "AGENTSCOPE_WEBUI_PORT=25173"
set "PLATFORM_API_PORT=38430"
set "PLATFORM_WEB_PORT=38429"

title Dobby 全部服务启动器

if not exist "%ROOT%start_agentscope.bat" (
    echo [失败] 缺少 start_agentscope.bat。
    goto FAILED
)

if not exist "%ROOT%start-frontend.bat" (
    echo [失败] 缺少 start-frontend.bat。
    goto FAILED
)

echo [Dobby] 正在停止旧服务和端口占用进程……
if exist "%ROOT%一键停止全部服务.bat" call "%ROOT%一键停止全部服务.bat" /quiet

echo.
echo [Dobby] 正在启动 AgentScope API 与管理端……
call "%ROOT%start_agentscope.bat"
if errorlevel 1 (
    echo [失败] AgentScope 启动脚本执行失败。
    goto FAILED
)

call :WAIT_PORT %AGENTSCOPE_PORT% 60 "AgentScope API"
if errorlevel 1 goto FAILED

echo.
echo [Dobby] 正在启动工程管理平台……
start "Dobby 工程管理平台" /D "%ROOT%" cmd.exe /c ""%ROOT%start-frontend.bat" --no-browser"

call :WAIT_PORT %PLATFORM_API_PORT% 60 "平台后端"
if errorlevel 1 goto FAILED
call :WAIT_PORT %PLATFORM_WEB_PORT% 60 "平台前端"
if errorlevel 1 goto FAILED
call :WAIT_PORT %AGENTSCOPE_WEBUI_PORT% 60 "Dobby 管理端"
if errorlevel 1 goto FAILED

echo.
echo [完成] Dobby 全部服务已启动。
echo [平台] http://服务器地址:%PLATFORM_WEB_PORT%/
echo [平台后端] http://127.0.0.1:%PLATFORM_API_PORT%/
echo [管理端] http://127.0.0.1:%AGENTSCOPE_WEBUI_PORT%/
echo [AgentScope API] http://127.0.0.1:%AGENTSCOPE_PORT%/
echo.
echo 停止全部服务请运行 一键停止全部服务.bat。
if /I not "%~1"=="--no-pause" pause
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
if !WAIT_COUNT! GEQ %WAIT_LIMIT% (
    echo [失败] 等待 %WAIT_NAME% 超时，端口 %WAIT_PORT_NUMBER% 未启动。
    exit /b 1
)
ping 127.0.0.1 -n 2 >nul
goto WAIT_PORT_LOOP

:FAILED
echo.
echo Dobby 服务启动失败，请检查已打开的服务窗口日志。
if /I not "%~1"=="--no-pause" pause
exit /b 1
