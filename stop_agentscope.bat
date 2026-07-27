@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title AgentScope Stop

cd /d "%~dp0"

if not defined AGENTSCOPE_PORT set "AGENTSCOPE_PORT=18642"
if not defined AGENTSCOPE_WEBUI_PORT set "AGENTSCOPE_WEBUI_PORT=25173"
if not defined AGENTSCOPE_WEBUI_HELPER_PORT set "AGENTSCOPE_WEBUI_HELPER_PORT=23000"

set "STOP_QUIET=0"
if /I "%~1"=="/quiet" set "STOP_QUIET=1"

if "!STOP_QUIET!"=="0" (
    echo [AgentScope] 正在停止 API、Web UI 和辅助服务……
)

rem 先按窗口标题终止启动器及其完整子进程树。
taskkill /F /T /FI "WINDOWTITLE eq AgentScope API*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq AgentScope Web UI*" >nul 2>nul

rem 再按固定端口清理脱离控制台的孤儿进程。
for %%P in (
    %AGENTSCOPE_PORT%
    %AGENTSCOPE_WEBUI_PORT%
    %AGENTSCOPE_WEBUI_HELPER_PORT%
) do call :KILL_PORT %%P

set "STOP_RETRY=0"

:WAIT_PORTS_FREE
set "PORTS_BUSY="
for %%P in (
    %AGENTSCOPE_PORT%
    %AGENTSCOPE_WEBUI_PORT%
    %AGENTSCOPE_WEBUI_HELPER_PORT%
) do call :CHECK_PORT %%P

if not defined PORTS_BUSY goto STOPPED

set /a STOP_RETRY+=1 >nul
if !STOP_RETRY! GEQ 10 goto STOP_FAILED

for %%P in (
    %AGENTSCOPE_PORT%
    %AGENTSCOPE_WEBUI_PORT%
    %AGENTSCOPE_WEBUI_HELPER_PORT%
) do call :KILL_PORT %%P
ping 127.0.0.1 -n 2 >nul
goto WAIT_PORTS_FREE

:STOPPED
if "!STOP_QUIET!"=="0" (
    echo [AgentScope] 已停止全部服务，端口均已释放。
    echo 按任意键关闭此窗口……
    pause >nul
)
exit /b 0

:STOP_FAILED
echo [错误] 无法在 10 秒内释放全部 AgentScope 端口。
if "!STOP_QUIET!"=="0" (
    echo 按任意键关闭此窗口……
    pause >nul
)
exit /b 1

:KILL_PORT
for /f "tokens=5" %%I in (
    'netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"'
) do (
    if not "%%I"=="0" (
        if "!STOP_QUIET!"=="0" (
            echo [AgentScope] 正在关闭端口 %~1 的进程 PID=%%I……
        )
        taskkill /F /T /PID %%I >nul 2>nul
    )
)
exit /b 0

:CHECK_PORT
for /f "tokens=5" %%I in (
    'netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"'
) do set "PORTS_BUSY=1"
exit /b 0
