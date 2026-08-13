@echo off
setlocal EnableExtensions
chcp 65001 >nul
title AgentScope 2.x Service

cd /d "%~dp0"

set "PYTHON_EXE=%~dp0python-3.13.14\python.exe"
set "AGENTSCOPE_HOME=%~dp0AgentScope"
set "AGENTSCOPE_CORE_HOME=%AGENTSCOPE_HOME%\agentscope"
set "RUNTIME_HOME=%~dp0data\agentscope"
set "SQLITE_PATH=%RUNTIME_HOME%\agentscope.db"
set "KNOWLEDGE_BLOB_HOME=%RUNTIME_HOME%\knowledge_blobs"
set "WEBUI_HOME=%AGENTSCOPE_HOME%\agentscope-web-ui"

if not defined AGENTSCOPE_HOST set "AGENTSCOPE_HOST=127.0.0.1"
if not defined AGENTSCOPE_PORT set "AGENTSCOPE_PORT=18642"
if not defined AGENTSCOPE_STORAGE set "AGENTSCOPE_STORAGE=postgresql"
if not defined AGENTSCOPE_WEBUI_PORT set "AGENTSCOPE_WEBUI_PORT=25173"
if not defined AGENTSCOPE_WEBUI_HELPER_PORT set "AGENTSCOPE_WEBUI_HELPER_PORT=23000"

if not exist "%PYTHON_EXE%" goto ERROR_PYTHON
if not exist "%AGENTSCOPE_CORE_HOME%\__init__.py" goto ERROR_CORE

"%PYTHON_EXE%" -c "import agentscope; from agentscope.app.storage import AsyncSQLAlchemyStorage; assert agentscope.__version__ == '2.0.6'" >nul
if errorlevel 1 goto ERROR_CORE_IMPORT

"%PYTHON_EXE%" -c "import aiosqlite, asyncpg, alembic, psycopg, pgvector, sqlalchemy, pypdf, pandas, pptx, openpyxl, xlrd, docx, pdfplumber, pypdfium2, PIL, rapidocr_onnxruntime" >nul
if errorlevel 1 goto ERROR_DEPENDENCIES
if not exist "%WEBUI_HOME%\package.json" goto ERROR_WEBUI

where pnpm >nul 2>nul
if errorlevel 1 goto ERROR_PNPM

if /I "%AGENTSCOPE_VALIDATE_ONLY%"=="1" exit /b 0
goto START_RUNTIME

:ERROR_PYTHON
echo [错误] 未找到项目内嵌 Python：%PYTHON_EXE%
pause
exit /b 1

:ERROR_CORE
echo [错误] 未找到项目内 AgentScope 核心目录：%AGENTSCOPE_CORE_HOME%
pause
exit /b 1

:ERROR_CORE_IMPORT
echo [错误] 无法导入项目内 AgentScope 2.0.6 核心。
pause
exit /b 1

:ERROR_DEPENDENCIES
echo [错误] AgentScope 知识库依赖不完整。
echo [提示] 请执行："%PYTHON_EXE%" -m pip install -r "%~dp0requirements-agentscope.txt"
pause
exit /b 1

:ERROR_WEBUI
echo [错误] 未找到 AgentScope Web UI：%WEBUI_HOME%
pause
exit /b 1

:ERROR_PNPM
echo [错误] 未找到 pnpm，请先安装 pnpm。
pause
exit /b 1

:START_RUNTIME

echo [AgentScope] 正在检查并强制关闭占用启动端口的旧进程……
taskkill /F /T /FI "WINDOWTITLE eq AgentScope API*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq AgentScope Web UI*" >nul 2>nul
for %%P in (%AGENTSCOPE_PORT% %AGENTSCOPE_WEBUI_PORT% %AGENTSCOPE_WEBUI_HELPER_PORT%) do call :KILL_PORT %%P

:WAIT_PORTS_FREE
set "PORTS_BUSY="
for %%P in (%AGENTSCOPE_PORT% %AGENTSCOPE_WEBUI_PORT% %AGENTSCOPE_WEBUI_HELPER_PORT%) do call :CHECK_PORT %%P
if not defined PORTS_BUSY goto PORTS_READY

if not defined PORT_KILL_RETRY set "PORT_KILL_RETRY=0"
set /a PORT_KILL_RETRY+=1 >nul
if %PORT_KILL_RETRY% GEQ 10 (
    echo [错误] 已持续强制关闭占用进程 10 秒，但仍有启动端口被占用。
    pause
    exit /b 1
)
for %%P in (%AGENTSCOPE_PORT% %AGENTSCOPE_WEBUI_PORT% %AGENTSCOPE_WEBUI_HELPER_PORT%) do call :KILL_PORT %%P
ping 127.0.0.1 -n 2 >nul
goto WAIT_PORTS_FREE

:PORTS_READY

if not exist "%WEBUI_HOME%\node_modules\.pnpm" (
    echo [AgentScope] 首次运行，正在安装官方 Web UI 依赖……
    pushd "%WEBUI_HOME%"
    call pnpm install --frozen-lockfile
    if errorlevel 1 (
        popd
        echo [错误] Web UI 依赖安装失败。
        pause
        exit /b 1
    )
    popd
)

set "AGENTSCOPE_RUNTIME_HOME=%RUNTIME_HOME%"
set "AGENTSCOPE_SQLITE_PATH=%SQLITE_PATH%"
set "AGENTSCOPE_KNOWLEDGE_BLOB_HOME=%KNOWLEDGE_BLOB_HOME%"

echo [AgentScope] Python 核心：%AGENTSCOPE_CORE_HOME%
echo [AgentScope] 核心版本：本地集成版 2.0.6
echo [AgentScope] 存储模式：%AGENTSCOPE_STORAGE%
echo [AgentScope] 运行数据：%RUNTIME_HOME%
if /I "%AGENTSCOPE_STORAGE%"=="sqlite" echo [AgentScope] SQLite 元数据：%SQLITE_PATH%
if /I "%AGENTSCOPE_STORAGE%"=="postgresql" echo [AgentScope] PostgreSQL schema：agentscope
echo [AgentScope] 知识库向量：PostgreSQL schema knowledge
echo [AgentScope] 知识库文件：%KNOWLEDGE_BLOB_HOME%
echo [AgentScope] 后端地址：http://%AGENTSCOPE_HOST%:%AGENTSCOPE_PORT%
echo [AgentScope] API 文档：http://%AGENTSCOPE_HOST%:%AGENTSCOPE_PORT%/docs
echo [AgentScope] Web UI：http://localhost:%AGENTSCOPE_WEBUI_PORT%
echo.

echo [AgentScope] 正在启动后端热重载进程……
start "AgentScope API" /D "%~dp0" "%PYTHON_EXE%" "%~dp0scripts\agentscope_dev_runner.py"

echo [AgentScope] 正在启动官方 Web UI 热更新进程……
start "AgentScope Web UI" /D "%WEBUI_HOME%" cmd.exe /k pnpm dev

echo [AgentScope] 已分别启动后端和 Web UI；停止时请运行 stop_agentscope.bat。
exit /b 0

:KILL_PORT
for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do (
    if not "%%I"=="0" (
        echo [AgentScope] 端口 %~1 已被 PID=%%I 占用，正在强制关闭……
        taskkill /F /T /PID %%I >nul 2>nul
    )
)
exit /b 0

:CHECK_PORT
for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do (
    set "PORTS_BUSY=1"
)
exit /b 0
