@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title AgentScope Stop

cd /d "%~dp0"

set "ROOT=%~dp0"
set "PROJECT_ROOT=%ROOT:~0,-1%"
set "PROCESS_CONTROL=%ROOT%scripts\dobby_process_control.ps1"
set "POWERSHELL_EXE=powershell.exe"
if not defined AGENTSCOPE_PORT set "AGENTSCOPE_PORT=18642"
if not defined AGENTSCOPE_WEBUI_PORT set "AGENTSCOPE_WEBUI_PORT=25173"
if not defined AGENTSCOPE_WEBUI_HELPER_PORT set "AGENTSCOPE_WEBUI_HELPER_PORT=23000"

set "STOP_QUIET=0"
set "STOP_DRY_RUN=0"
for %%A in (%*) do (
    if /I "%%~A"=="/quiet" set "STOP_QUIET=1"
    if /I "%%~A"=="/dry-run" set "STOP_DRY_RUN=1"
)
set "CONTROL_MODE="
if "!STOP_DRY_RUN!"=="1" set "CONTROL_MODE=-DryRun"

where pwsh.exe >nul 2>nul
if not errorlevel 1 set "POWERSHELL_EXE=pwsh.exe"

if "!STOP_QUIET!"=="0" (
    echo [AgentScope] 正在停止 API、Web UI 和辅助服务……
)

if not exist "%PROCESS_CONTROL%" (
    echo [错误] 缺少安全进程控制脚本：%PROCESS_CONTROL%
    if "!STOP_QUIET!"=="0" pause >nul
    exit /b 1
)

if "!STOP_QUIET!"=="1" (
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROCESS_CONTROL%" -Action StopPorts -ProjectRoot "%PROJECT_ROOT%" -Ports "%AGENTSCOPE_PORT%,%AGENTSCOPE_WEBUI_PORT%,%AGENTSCOPE_WEBUI_HELPER_PORT%" -Quiet !CONTROL_MODE!
) else (
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROCESS_CONTROL%" -Action StopPorts -ProjectRoot "%PROJECT_ROOT%" -Ports "%AGENTSCOPE_PORT%,%AGENTSCOPE_WEBUI_PORT%,%AGENTSCOPE_WEBUI_HELPER_PORT%" !CONTROL_MODE!
)
set "STOP_EXIT=!ERRORLEVEL!"

if not "!STOP_EXIT!"=="0" (
    if "!STOP_QUIET!"=="0" (
        echo [AgentScope] 未扩大查杀范围；请根据上方提示处理端口冲突。
        pause >nul
    )
    exit /b !STOP_EXIT!
)

if "!STOP_QUIET!"=="0" (
    if "!STOP_DRY_RUN!"=="1" (
        echo [AgentScope] DryRun 安全检查完成，未结束任何进程。
    ) else (
        echo [AgentScope] 已安全停止 API、Web UI 和辅助服务。
    )
    echo 按任意键关闭此窗口……
    pause >nul
)
exit /b 0
