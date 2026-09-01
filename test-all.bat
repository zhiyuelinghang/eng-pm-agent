@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "PROJECT_ROOT=%~dp0"
set "PROJECT_PYTHON=%PROJECT_ROOT%python-3.13.14\python.exe"

if not exist "%PROJECT_PYTHON%" (
    echo [失败] 缺少项目便携 Python：%PROJECT_PYTHON%
    exit /b 1
)

"%PROJECT_PYTHON%" "%PROJECT_ROOT%scripts\run_project_tests.py" %*
exit /b %ERRORLEVEL%
