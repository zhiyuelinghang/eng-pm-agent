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

if not defined AGENTSCOPE_HOST set "AGENTSCOPE_HOST=127.0.0.1"
if not defined AGENTSCOPE_PORT set "AGENTSCOPE_PORT=18642"
if not defined AGENTSCOPE_STORAGE set "AGENTSCOPE_STORAGE=sqlite"
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

"%PYTHON_EXE%" -c "import agentscope; import aiosqlite, qdrant_client, sqlalchemy, openpyxl, xlrd, docx, pptx, pdfplumber, pypdfium2, PIL, rapidocr_onnxruntime; assert agentscope.__version__ == '2.0.5'" >nul
if errorlevel 1 (
    echo [错误] 随包携带的 AgentScope Python 依赖验证失败。
    pause
    exit /b 1
)

taskkill /F /T /FI "WINDOWTITLE eq Dobby AgentScope API*" >nul 2>nul
taskkill /F /T /FI "WINDOWTITLE eq Dobby Management Web*" >nul 2>nul
for %%P in (%AGENTSCOPE_PORT% %AGENTSCOPE_WEBUI_PORT%) do call :KILL_PORT %%P

set "AGENTSCOPE_RUNTIME_HOME=%RUNTIME_HOME%"
set "AGENTSCOPE_SQLITE_PATH=%RUNTIME_HOME%\agentscope.db"
set "AGENTSCOPE_QDRANT_HOME=%RUNTIME_HOME%\qdrant"
set "AGENTSCOPE_KNOWLEDGE_BLOB_HOME=%RUNTIME_HOME%\knowledge_blobs"

echo [AgentScope] 正在启动 API：http://%AGENTSCOPE_HOST%:%AGENTSCOPE_PORT%
start "Dobby AgentScope API" /D "%PROJECT_ROOT%" cmd.exe /c ""%PYTHON_EXE%" -m uvicorn scripts.agentscope_dev_app:app --app-dir "%PROJECT_ROOT%" --host %AGENTSCOPE_HOST% --port %AGENTSCOPE_PORT%"

echo [AgentScope] 正在启动预构建管理端：http://127.0.0.1:%AGENTSCOPE_WEBUI_PORT%
start "Dobby Management Web" /D "%ROOT%" "%PYTHON_EXE%" "%WEB_GATEWAY%" --mode agentscope --host 127.0.0.1 --port %AGENTSCOPE_WEBUI_PORT%

echo [AgentScope] 启动命令已执行，服务器无需 Node.js、npm 或 pnpm。
exit /b 0

:KILL_PORT
for /f "tokens=5" %%I in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do (
    if not "%%I"=="0" (
        echo [AgentScope] 端口 %~1 被 PID=%%I 占用，正在关闭……
        taskkill /F /T /PID %%I >nul 2>nul
    )
)
exit /b 0
