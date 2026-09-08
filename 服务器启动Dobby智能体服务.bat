@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "ROOT=%~dp0"
set "PROJECT_ROOT=%ROOT:~0,-1%"
set "PYTHON_EXE=%ROOT%python-3.13.14\python.exe"
set "AGENTSCOPE_CORE=%ROOT%AgentScope\agentscope"
set "WEBUI_DIST=%ROOT%AgentScope\agentscope-web-ui\frontend\dist"
set "WEB_GATEWAY=%ROOT%scripts\dobby_web_gateway.py"
set "RUNTIME_HOME=%ROOT%data\agentscope"
set "PROCESS_CONTROL=%ROOT%scripts\dobby_process_control.ps1"
set "POWERSHELL_EXE=powershell.exe"

where pwsh.exe >nul 2>nul
if not errorlevel 1 set "POWERSHELL_EXE=pwsh.exe"

if not defined AGENTSCOPE_HOST set "AGENTSCOPE_HOST=127.0.0.1"
if not defined AGENTSCOPE_PORT set "AGENTSCOPE_PORT=18642"
if not defined AGENTSCOPE_STORAGE set "AGENTSCOPE_STORAGE=postgresql"
if not defined AGENTSCOPE_WEBUI_PORT set "AGENTSCOPE_WEBUI_PORT=25173"

title Dobby 服务器智能体服务启动器

if not exist "%PYTHON_EXE%" (
    echo [错误] 缺少项目便携 Python：%PYTHON_EXE%
    pause
    exit /b 1
)

if not exist "%AGENTSCOPE_CORE%\__init__.py" (
    echo [错误] 缺少 AgentScope 核心：%AGENTSCOPE_CORE%
    pause
    exit /b 1
)

if not exist "%WEBUI_DIST%\index.html" (
    echo [错误] 缺少预构建 Dobby 管理端：%WEBUI_DIST%\index.html
    pause
    exit /b 1
)

if not exist "%WEB_GATEWAY%" (
    echo [错误] 缺少 Python Web 网关：%WEB_GATEWAY%
    pause
    exit /b 1
)

if not exist "%PROCESS_CONTROL%" (
    echo [错误] 缺少安全进程控制脚本：%PROCESS_CONTROL%
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import os, sys; sys.path.insert(0, os.environ['PROJECT_ROOT']); import agentscope; from agentscope.app.storage import AsyncSQLAlchemyStorage; import aiosqlite, asyncpg, psycopg, pgvector, sqlalchemy, openpyxl, xlrd, docx, pptx, pdfplumber, pypdfium2, PIL, rapidocr_onnxruntime; assert agentscope.__version__ == '2.0.7'" >nul
if errorlevel 1 (
    echo [错误] 随包携带的 AgentScope Python 依赖验证失败。
    pause
    exit /b 1
)

echo [AgentScope] 正在安全检查启动端口，仅停止身份已确认的旧 Dobby 服务……
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROCESS_CONTROL%" -Action StopPorts -ProjectRoot "%PROJECT_ROOT%" -Ports "%AGENTSCOPE_PORT%,%AGENTSCOPE_WEBUI_PORT%"
if errorlevel 1 (
    echo [错误] AgentScope 启动端口存在无法安全处理的占用，已取消启动。
    pause
    exit /b 1
)

set "AGENTSCOPE_RUNTIME_HOME=%RUNTIME_HOME%"
set "AGENTSCOPE_SQLITE_PATH=%RUNTIME_HOME%\agentscope.db"
set "AGENTSCOPE_KNOWLEDGE_BLOB_HOME=%RUNTIME_HOME%\knowledge_blobs"

echo [AgentScope] 正在启动 API：http://%AGENTSCOPE_HOST%:%AGENTSCOPE_PORT%
start "Dobby AgentScope API" /D "%PROJECT_ROOT%" cmd.exe /c ""%PYTHON_EXE%" -m uvicorn scripts.agentscope_dev_app:app --app-dir "%PROJECT_ROOT%" --host %AGENTSCOPE_HOST% --port %AGENTSCOPE_PORT%"

echo [AgentScope] 正在启动预构建管理端：http://127.0.0.1:%AGENTSCOPE_WEBUI_PORT%
start "Dobby Management Web" /D "%ROOT%" "%PYTHON_EXE%" "%WEB_GATEWAY%" --mode agentscope --host 127.0.0.1 --port %AGENTSCOPE_WEBUI_PORT%

echo [AgentScope] 正在登记本次启动的服务 PID……
"%POWERSHELL_EXE%" -NoProfile -ExecutionPolicy Bypass -File "%PROCESS_CONTROL%" -Action RegisterPorts -ProjectRoot "%PROJECT_ROOT%" -Ports "%AGENTSCOPE_PORT%,%AGENTSCOPE_WEBUI_PORT%" -WaitSeconds 60
if errorlevel 1 (
    echo [错误] AgentScope 服务 PID 登记失败。服务不会被模糊查杀，请检查启动窗口日志。
    pause
    exit /b 1
)

echo [AgentScope] 启动命令已执行，服务器无需 Node.js、npm 或 pnpm。
exit /b 0
