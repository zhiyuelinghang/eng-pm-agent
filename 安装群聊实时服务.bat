@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "ROOT=%~dp0"
set "INSTALLER=%ROOT%scripts\install_centrifugo.ps1"
set "POWERSHELL_EXE=powershell.exe"

where pwsh.exe >nul 2>nul
if not errorlevel 1 set "POWERSHELL_EXE=pwsh.exe"

if not exist "%INSTALLER%" (
    echo [失败] 缺少 Centrifugo 安装脚本：%INSTALLER%
    exit /b 1
)

echo [Dobby] 正在下载并校验 Centrifugo Windows 单文件版本……
echo [Dobby] 使用 %POWERSHELL_EXE% 执行安装脚本。
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%INSTALLER%"
if errorlevel 1 (
    echo [失败] Centrifugo 安装失败。
    exit /b 1
)

echo [完成] 群聊实时服务已安装，不需要 Docker。
if /I not "%~1"=="--no-pause" pause
exit /b 0
