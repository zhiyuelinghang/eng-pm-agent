@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "STOP_QUIET=0"
if /I "%~1"=="/quiet" set "STOP_QUIET=1"

title Dobby 一键停止全部服务

if "!STOP_QUIET!"=="0" echo [Dobby] 正在停止全部服务……

if exist "%ROOT%stop_agentscope.bat" (
    call "%ROOT%stop_agentscope.bat" /quiet
)

taskkill /F /T /FI "WINDOWTITLE eq Dobby 工程管理平台*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq Dobby Platform Server*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq Dobby Platform API*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq Dobby AgentScope API*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq Dobby Management Web*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq Eng PM Agent AI Workspace*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq Eng PM Agent API*" >nul 2>nul

for %%P in (38429 38430 18642 25173 23000) do call :KILL_PORT %%P

set "STOP_RETRY=0"

:WAIT_PORTS_FREE
set "PORTS_BUSY="
for %%P in (38429 38430 18642 25173 23000) do call :CHECK_PORT %%P
if not defined PORTS_BUSY goto STOPPED

set /a STOP_RETRY+=1 >nul
if !STOP_RETRY! GEQ 10 goto STOP_FAILED
for %%P in (38429 38430 18642 25173 23000) do call :KILL_PORT %%P
ping 127.0.0.1 -n 2 >nul
goto WAIT_PORTS_FREE

:STOPPED
if "!STOP_QUIET!"=="0" (
    echo [完成] Dobby 全部服务已停止，端口均已释放。
    pause
)
exit /b 0

:STOP_FAILED
echo [失败] 无法在 10 秒内释放全部服务端口。
if "!STOP_QUIET!"=="0" pause
exit /b 1

:KILL_PORT
for /f "tokens=5" %%I in (
    'netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"'
) do (
    if not "%%I"=="0" (
        if "!STOP_QUIET!"=="0" echo [Dobby] 正在关闭端口 %~1 的进程 PID=%%I……
        taskkill /F /T /PID %%I >nul 2>nul
    )
)
exit /b 0

:CHECK_PORT
for /f "tokens=5" %%I in (
    'netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"'
) do set "PORTS_BUSY=1"
exit /b 0
