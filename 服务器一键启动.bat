@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "AGENTSCOPE_PORT=18642"
set "AGENTSCOPE_WEBUI_PORT=25173"
set "PLATFORM_API_PORT=38430"
set "PLATFORM_WEB_PORT=38429"
set "DOBBY_REALTIME_PORT=38431"
set "PROJECT_ROOT=%ROOT:~0,-1%"
set "PROCESS_CONTROL=%ROOT%scripts\dobby_process_control.ps1"
set "POWERSHELL_EXE=powershell.exe"

where pwsh.exe >nul 2>nul
if not errorlevel 1 set "POWERSHELL_EXE=pwsh.exe"

title Dobby 服务器一键启动

if not exist "%ROOT%服务器启动Dobby智能体服务.bat" (
    echo [失败] 缺少“服务器启动Dobby智能体服务.bat”。
    goto FAILED
)

if not exist "%ROOT%服务器启动工程管理平台.bat" (
    echo [失败] 缺少“服务器启动工程管理平台.bat”。
    goto FAILED
)

if not exist "%ROOT%start-centrifugo.bat" (
    echo [失败] 缺少 start-centrifugo.bat。
    goto FAILED
)

echo [Dobby] 正在停止旧服务和端口占用进程……
if exist "%ROOT%一键停止全部服务.bat" (
    call "%ROOT%一键停止全部服务.bat" /quiet
    if errorlevel 1 (
        echo [失败] 旧服务未能安全停止；为保护服务器上的其他程序，本次启动已取消。
        goto FAILED
    )
)

echo.
echo [Dobby] 正在启动项目群聊实时服务……
call "%ROOT%start-centrifugo.bat"
if errorlevel 1 goto FAILED
set "CENTRIFUGO_ENABLED=true"
call :WAIT_PORT %DOBBY_REALTIME_PORT% 30 "群聊实时服务"
if errorlevel 1 goto FAILED

echo.
echo [Dobby] 正在启动 AgentScope API 与管理端……
call "%ROOT%服务器启动Dobby智能体服务.bat"
if errorlevel 1 goto FAILED
call :WAIT_PORT %AGENTSCOPE_PORT% 60 "AgentScope API"
if errorlevel 1 goto FAILED
call :WAIT_PORT %AGENTSCOPE_WEBUI_PORT% 60 "Dobby 管理端"
if errorlevel 1 goto FAILED

echo.
echo [Dobby] 正在启动工程管理平台……
start "Dobby Platform Server" /D "%ROOT%" cmd.exe /c ""%ROOT%服务器启动工程管理平台.bat""
call :WAIT_PORT %PLATFORM_API_PORT% 60 "平台后端"
if errorlevel 1 goto FAILED
call :WAIT_PORT %PLATFORM_WEB_PORT% 60 "平台前端"
if errorlevel 1 goto FAILED

"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROCESS_CONTROL%" -Action RegisterPorts -ProjectRoot "%PROJECT_ROOT%" -Ports "%PLATFORM_WEB_PORT%,%PLATFORM_API_PORT%,%DOBBY_REALTIME_PORT%,%AGENTSCOPE_PORT%,%AGENTSCOPE_WEBUI_PORT%" -WaitSeconds 10 -Quiet
if errorlevel 1 (
    echo [失败] 服务已启动，但 PID 安全登记不完整；为避免后续误杀，本次启动标记为失败。
    goto FAILED
)

echo.
echo [完成] Dobby 服务器全部服务已启动。
echo [平台] http://服务器地址:%PLATFORM_WEB_PORT%/
echo [平台后端] http://127.0.0.1:%PLATFORM_API_PORT%/
echo [管理端] http://127.0.0.1:%AGENTSCOPE_WEBUI_PORT%/
echo [AgentScope API] http://127.0.0.1:%AGENTSCOPE_PORT%/
echo [群聊实时服务] ws://服务器地址:%DOBBY_REALTIME_PORT%/connection/websocket
echo [运行环境] 仅使用项目便携 Python，不需要 Node.js。
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
echo Dobby 服务器启动失败，请检查已打开的服务窗口日志。
if /I not "%~1"=="--no-pause" pause
exit /b 1
