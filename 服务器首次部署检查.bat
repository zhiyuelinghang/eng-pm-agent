@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "ROOT=%~dp0"
set "PROJECT_ROOT=%ROOT:~0,-1%"
set "PYTHON_EXE=%ROOT%python-3.13.14\python.exe"
set "PLATFORM_DIST=%ROOT%frontend\dist"
set "AGENTSCOPE_DIST=%ROOT%AgentScope\agentscope-web-ui\frontend\dist"
set "NO_PAUSE=0"

for %%A in (%*) do (
    if /I "%%~A"=="--no-pause" set "NO_PAUSE=1"
)

title Dobby 服务器首次部署检查

echo [检查] 正在检查服务器部署文件……

if not exist "%PYTHON_EXE%" (
    echo [失败] 未找到项目内嵌 Python：
    echo %PYTHON_EXE%
    echo 请保留服务器原有 python-3.13.14 目录。
    goto FAILED
)

if not exist "%ROOT%python-3.13.14\python313._pth" (
    echo [失败] 缺少 python-3.13.14\python313._pth。
    goto FAILED
)

if not exist "%ROOT%backend\app\main.py" (
    echo [失败] 缺少平台后端代码。
    goto FAILED
)

if not exist "%ROOT%AgentScope\agentscope\__init__.py" (
    echo [失败] 缺少 AgentScope 核心代码。
    goto FAILED
)

if not exist "%PLATFORM_DIST%\index.html" (
    echo [失败] 缺少开发机预构建的平台前端：
    echo %PLATFORM_DIST%\index.html
    goto FAILED
)

if not exist "%AGENTSCOPE_DIST%\index.html" (
    echo [失败] 缺少开发机预构建的 Dobby 管理端：
    echo %AGENTSCOPE_DIST%\index.html
    goto FAILED
)

if not exist "%ROOT%scripts\dobby_web_gateway.py" (
    echo [失败] 缺少 Python Web 网关。
    goto FAILED
)

if not exist "%ROOT%scripts\dobby_process_control.ps1" (
    echo [失败] 缺少安全进程控制脚本。
    goto FAILED
)

if not exist "%ROOT%utils\config.py" (
    echo [失败] 缺少 Dobby 记忆与上下文运行模块：utils\config.py。
    goto FAILED
)

if not exist "%ROOT%start-centrifugo.bat" (
    echo [失败] 缺少群聊实时服务启动入口：start-centrifugo.bat。
    goto FAILED
)

if not exist "%ROOT%安装群聊实时服务.bat" (
    echo [失败] 缺少群聊实时服务安装入口。
    goto FAILED
)

if not exist "%ROOT%scripts\install_centrifugo.ps1" (
    echo [失败] 缺少 Centrifugo 安装脚本。
    goto FAILED
)

if not exist "%ROOT%backend\scripts\generate_centrifugo_config.py" (
    echo [失败] 缺少群聊实时服务配置生成脚本。
    goto FAILED
)

if not exist "%ROOT%runtime\centrifugo\centrifugo.exe" (
    echo [失败] 首次部署内容不完整，缺少群聊实时服务运行程序：
    echo %ROOT%runtime\centrifugo\centrifugo.exe
    echo 请重新解压完整的 dobby-server-first-install.zip。
    echo “安装群聊实时服务.bat”仅作为损坏修复或手动升级入口。
    goto FAILED
)

if not exist "%ROOT%.env" (
    if not exist "%ROOT%.env.example" (
        echo [失败] 缺少 .env 和 .env.example。
        goto FAILED
    )
    copy /Y "%ROOT%.env.example" "%ROOT%.env" >nul
    echo [需要配置] 已根据 .env.example 创建服务器 .env。
    echo 请先完成 .env 配置，再重新运行本脚本。
    goto CONFIG_REQUIRED
)

findstr /C:"请替换" /C:"请设置" "%ROOT%.env" >nul 2>nul
if not errorlevel 1 (
    echo [需要配置] .env 中仍存在示例占位值。
    echo 请完成 .env 配置后重新运行本脚本。
    goto CONFIG_REQUIRED
)

echo.
echo [检查] 正在验证随包携带的 Python 与 AgentScope 运行环境……
"%PYTHON_EXE%" -c "import agentscope; import aiosqlite, asyncpg, alembic, psycopg, pgvector, sqlalchemy, pypdf, pandas, openpyxl, xlrd, docx, pptx, pdfplumber, pypdfium2, PIL, rapidocr_onnxruntime; assert agentscope.__version__ == '2.0.7'"
if errorlevel 1 (
    echo [失败] AgentScope Python 环境验证失败。
    goto FAILED
)
echo [检查] AgentScope Python 环境验证通过。

"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, r'%PROJECT_ROOT%'); from scripts.agentscope_dev_app import app; assert app is not None"
if errorlevel 1 (
    echo [失败] Dobby 服务配置验证失败，请检查根目录 .env。
    goto FAILED
)
echo [检查] Dobby 服务配置验证通过。

"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, r'%PROJECT_ROOT%'); from scripts.dobby_web_gateway import create_gateway; create_gateway('platform'); create_gateway('agentscope')"
if errorlevel 1 (
    echo [失败] 预构建页面或 Python Web 网关验证失败。
    goto FAILED
)
echo [检查] 平台前端与 Dobby 管理端验证通过。

echo.
echo [完成] 服务器程序首次部署检查完成。
echo [完成] 本脚本没有安装任何依赖，服务器不需要 Node.js、npm 或 pnpm。
echo [下一步] 可运行 服务器一键启动.bat。
goto FINISH

:CONFIG_REQUIRED
echo.
echo 部署检查尚未完成，完成 .env 配置后请重新运行。
if "%NO_PAUSE%"=="0" pause
exit /b 2

:FAILED
echo.
echo 服务器程序首次部署检查失败。
if "%NO_PAUSE%"=="0" pause
exit /b 1

:FINISH
if "%NO_PAUSE%"=="0" pause
exit /b 0
