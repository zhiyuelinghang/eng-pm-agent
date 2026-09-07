@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "PYTHON_EXE=%ROOT%python-3.13.14\python.exe"
set "DOBBY_REALTIME_EXE=%ROOT%runtime\centrifugo\centrifugo.exe"
set "DOBBY_REALTIME_CONFIG=%ROOT%runtime\centrifugo\config.json"
set "DOBBY_REALTIME_PORT=38431"

rem These names belong to the platform app, not to Centrifugo's own env schema.
set "CENTRIFUGO_ENABLED="
set "CENTRIFUGO_PORT="

if not exist "%DOBBY_REALTIME_EXE%" (
    echo [失败] 缺少群聊实时服务运行程序：%DOBBY_REALTIME_EXE%
    echo 首次部署请重新解压 dobby-server-first-install.zip。
    echo 已部署服务器可运行“安装群聊实时服务.bat”进行修复。
    exit /b 1
)
if not exist "%PYTHON_EXE%" (
    echo [失败] 缺少项目便携 Python：%PYTHON_EXE%
    exit /b 1
)
netstat -ano | findstr /R /C:":%DOBBY_REALTIME_PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [就绪] 群聊实时服务已监听端口 %DOBBY_REALTIME_PORT%。
    exit /b 0
)

pushd "%ROOT%"
"%PYTHON_EXE%" -c "import sys; sys.path.insert(0, r'%ROOT%.'); from backend.scripts.generate_centrifugo_config import main; main()"
if errorlevel 1 (
    popd
    echo [失败] 无法生成群聊实时服务配置。
    exit /b 1
)
popd

start "Dobby Realtime" /D "%ROOT%runtime\centrifugo" /b "%DOBBY_REALTIME_EXE%" --config="%DOBBY_REALTIME_CONFIG%"
set "WAIT_COUNT=0"
:WAIT_REALTIME
netstat -ano | findstr /R /C:":%DOBBY_REALTIME_PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 (
    echo [就绪] 群聊实时服务已监听端口 %DOBBY_REALTIME_PORT%。
    exit /b 0
)
set /a WAIT_COUNT+=1 >nul
if !WAIT_COUNT! GEQ 15 (
    echo [失败] 群聊实时服务启动超时。
    exit /b 1
)
ping 127.0.0.1 -n 2 >nul
goto WAIT_REALTIME
