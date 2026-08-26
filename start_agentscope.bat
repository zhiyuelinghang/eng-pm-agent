@echo off
setlocal EnableExtensions
chcp 65001 >nul
title AgentScope 2.x Service

cd /d "%~dp0"

set "ROOT=%~dp0"
set "PROJECT_ROOT=%ROOT:~0,-1%"
set "PYTHON_EXE=%~dp0python-3.13.14\python.exe"
set "AGENTSCOPE_HOME=%~dp0AgentScope"
set "AGENTSCOPE_CORE_HOME=%AGENTSCOPE_HOME%\agentscope"
set "RUNTIME_HOME=%~dp0data\agentscope"
set "SQLITE_PATH=%RUNTIME_HOME%\agentscope.db"
set "KNOWLEDGE_BLOB_HOME=%RUNTIME_HOME%\knowledge_blobs"
set "WEBUI_HOME=%AGENTSCOPE_HOME%\agentscope-web-ui"
set "PROCESS_CONTROL=%ROOT%scripts\dobby_process_control.ps1"
set "POWERSHELL_EXE=powershell.exe"

where pwsh.exe >nul 2>nul
if not errorlevel 1 set "POWERSHELL_EXE=pwsh.exe"

if not defined AGENTSCOPE_HOST set "AGENTSCOPE_HOST=127.0.0.1"
if not defined AGENTSCOPE_PORT set "AGENTSCOPE_PORT=18642"
if not defined AGENTSCOPE_STORAGE set "AGENTSCOPE_STORAGE=postgresql"
if not defined AGENTSCOPE_WEBUI_PORT set "AGENTSCOPE_WEBUI_PORT=25173"
if not defined AGENTSCOPE_WEBUI_HELPER_PORT set "AGENTSCOPE_WEBUI_HELPER_PORT=23000"

if not exist "%PYTHON_EXE%" goto ERROR_PYTHON
if not exist "%AGENTSCOPE_CORE_HOME%\__init__.py" goto ERROR_CORE

"%PYTHON_EXE%" -c "import agentscope; from agentscope.app.storage import AsyncSQLAlchemyStorage; assert agentscope.__version__ == '2.0.7'" >nul
if errorlevel 1 goto ERROR_CORE_IMPORT

"%PYTHON_EXE%" -c "import aiosqlite, asyncpg, alembic, psycopg, pgvector, sqlalchemy, pypdf, pandas, pptx, openpyxl, xlrd, docx, pdfplumber, pypdfium2, PIL, rapidocr_onnxruntime, langgraph, graphiti_core, neo4j, sentence_transformers, torch, tiktoken, lightrag" >nul
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
echo [错误] 无法导入项目内 AgentScope 2.0.7 核心。
pause
exit /b 1

:ERROR_DEPENDENCIES
echo [错误] AgentScope、知识库或完整 Dobby 记忆依赖不完整。
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

if not exist "%PROCESS_CONTROL%" (
    echo [错误] 缺少安全进程控制脚本：%PROCESS_CONTROL%
    pause
    exit /b 1
)

echo [AgentScope] 正在安全检查启动端口，仅停止身份已确认的旧 Dobby 服务……
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROCESS_CONTROL%" -Action StopPorts -ProjectRoot "%PROJECT_ROOT%" -Ports "%AGENTSCOPE_PORT%,%AGENTSCOPE_WEBUI_PORT%,%AGENTSCOPE_WEBUI_HELPER_PORT%"
if errorlevel 1 (
    echo [错误] AgentScope 启动端口存在无法安全处理的占用，已取消启动。
    pause
    exit /b 1
)

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
echo [AgentScope] 核心版本：本地集成版 2.0.7
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
start "AgentScope Web UI" /D "%WEBUI_HOME%" cmd.exe /c pnpm dev

echo [AgentScope] 正在登记本次启动的服务 PID……
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROCESS_CONTROL%" -Action RegisterPorts -ProjectRoot "%PROJECT_ROOT%" -Ports "%AGENTSCOPE_PORT%,%AGENTSCOPE_WEBUI_PORT%,%AGENTSCOPE_WEBUI_HELPER_PORT%" -WaitSeconds 60
if errorlevel 1 (
    echo [错误] AgentScope 服务 PID 登记失败。服务不会被模糊查杀，请检查启动窗口日志。
    pause
    exit /b 1
)

echo [AgentScope] 已分别启动后端和 Web UI；停止时请运行 stop_agentscope.bat。
exit /b 0
