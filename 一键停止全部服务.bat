@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "PROJECT_ROOT=%ROOT:~0,-1%"
set "PROCESS_CONTROL=%ROOT%scripts\dobby_process_control.ps1"
set "POWERSHELL_EXE=powershell.exe"
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

title Dobby 一键停止全部服务

if "!STOP_QUIET!"=="0" echo [Dobby] 正在停止全部服务……

if not exist "%PROCESS_CONTROL%" (
    echo [失败] 缺少安全进程控制脚本：%PROCESS_CONTROL%
    if "!STOP_QUIET!"=="0" pause
    exit /b 1
)

if "!STOP_QUIET!"=="1" (
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROCESS_CONTROL%" -Action StopPorts -ProjectRoot "%PROJECT_ROOT%" -Ports "38429,38430,38431,18642,25173,23000" -Quiet !CONTROL_MODE!
) else (
    "%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROCESS_CONTROL%" -Action StopPorts -ProjectRoot "%PROJECT_ROOT%" -Ports "38429,38430,38431,18642,25173,23000" !CONTROL_MODE!
)
set "STOP_EXIT=!ERRORLEVEL!"

if not "!STOP_EXIT!"=="0" (
    if "!STOP_EXIT!"=="2" (
        echo [已保护] 检测到非 Dobby 进程占用服务端口，未结束该进程。
    ) else (
        echo [失败] Dobby 服务未能全部安全停止，请查看上方信息和 data\runtime\process-control.log。
    )
    if "!STOP_QUIET!"=="0" pause
    exit /b !STOP_EXIT!
)

if "!STOP_QUIET!"=="0" (
    if "!STOP_DRY_RUN!"=="1" (
        echo [完成] DryRun 安全检查完成，未结束任何进程。
    ) else (
        echo [完成] Dobby 全部服务已安全停止。
    )
    pause
)
exit /b 0
