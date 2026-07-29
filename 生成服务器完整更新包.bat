@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

set "ROOT=%~dp0"
set "OUTPUT_ROOT=%ROOT%更新文件"
set "UPDATE_NAME=server-update"
set "FIRST_NAME=server-first-install"
set "UPDATE_TARGET=%OUTPUT_ROOT%\%UPDATE_NAME%"
set "FIRST_TARGET=%OUTPUT_ROOT%\%FIRST_NAME%"
set "UPDATE_ARCHIVE=%OUTPUT_ROOT%\dobby-server-update.zip"
set "FIRST_ARCHIVE=%OUTPUT_ROOT%\dobby-server-first-install.zip"

title 生成 Dobby 服务器更新包

call :REQUIRE_FILE "backend\app\main.py"
if errorlevel 1 goto FAILED
call :REQUIRE_FILE "frontend\package.json"
if errorlevel 1 goto FAILED
call :REQUIRE_FILE "AgentScope\agentscope\__init__.py"
if errorlevel 1 goto FAILED
call :REQUIRE_FILE "AgentScope\agentscope-web-ui\package.json"
if errorlevel 1 goto FAILED
call :REQUIRE_FILE "scripts\agentscope_dev_app.py"
if errorlevel 1 goto FAILED
call :REQUIRE_FILE "scripts\dobby_agent_tools.py"
if errorlevel 1 goto FAILED
call :REQUIRE_FILE "scripts\dobby_web_gateway.py"
if errorlevel 1 goto FAILED
call :REQUIRE_FILE "python-3.13.14\python.exe"
if errorlevel 1 goto FAILED

where npm.cmd >nul 2>nul
if errorlevel 1 (
    echo [失败] 开发机未找到 npm.cmd，无法构建平台前端。
    goto FAILED
)

where pnpm.cmd >nul 2>nul
if errorlevel 1 (
    echo [失败] 开发机未找到 pnpm.cmd，无法构建 Dobby 管理端。
    goto FAILED
)

echo [构建] 所有 Node.js 构建均在开发机完成。
echo [构建] 服务器不需要 Node.js、npm、pnpm 或联网安装依赖。
echo.

call :BUILD_PLATFORM_FRONTEND
if errorlevel 1 goto FAILED
call :BUILD_AGENTSCOPE_FRONTEND
if errorlevel 1 goto FAILED

echo.
echo [更新包] 正在整理程序代码和预构建页面……

for %%D in ("%UPDATE_TARGET%" "%FIRST_TARGET%") do (
    if exist "%%~D" rmdir /S /Q "%%~D"
    if exist "%%~D" (
        echo [失败] 无法清理旧输出目录：%%~D
        goto FAILED
    )
)

mkdir "%UPDATE_TARGET%" >nul 2>nul
if errorlevel 1 goto COPY_FAILED

call :COPY_CODE_DIR "backend" "backend"
if errorlevel 1 goto FAILED
call :COPY_CODE_DIR "frontend" "frontend"
if errorlevel 1 goto FAILED
call :COPY_CODE_DIR "AgentScope" "AgentScope"
if errorlevel 1 goto FAILED
call :COPY_CODE_DIR "scripts" "scripts"
if errorlevel 1 goto FAILED

mkdir "%UPDATE_TARGET%\python-3.13.14" >nul 2>nul
copy /Y "%ROOT%python-3.13.14\python313._pth" "%UPDATE_TARGET%\python-3.13.14\python313._pth" >nul
if errorlevel 1 goto COPY_FAILED

for %%F in (
    ".env.example"
    "README.md"
    "服务器部署说明.md"
    "requirements-agentscope.txt"
    "服务器首次部署检查.bat"
    "服务器启动Dobby智能体服务.bat"
    "服务器启动工程管理平台.bat"
    "服务器一键启动.bat"
    "一键停止全部服务.bat"
) do (
    if not exist "%ROOT%%%~F" (
        echo [失败] 缺少更新包根文件：%%~F
        goto FAILED
    )
    copy /Y "%ROOT%%%~F" "%UPDATE_TARGET%\%%~F" >nul
    if errorlevel 1 goto COPY_FAILED
)

call :WRITE_VERSION "%UPDATE_TARGET%\VERSION.txt" "日常更新包" "不包含便携 Python 主体"
if errorlevel 1 goto FAILED

echo [更新包] 正在生成首次部署目录并加入完整便携 Python……
mkdir "%FIRST_TARGET%" >nul 2>nul
robocopy "%UPDATE_TARGET%" "%FIRST_TARGET%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP >nul
set "ROBOCOPY_EXIT=!ERRORLEVEL!"
if !ROBOCOPY_EXIT! GEQ 8 goto COPY_FAILED

robocopy "%ROOT%python-3.13.14" "%FIRST_TARGET%\python-3.13.14" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XD __pycache__ /XF *.pyc >nul
set "ROBOCOPY_EXIT=!ERRORLEVEL!"
if !ROBOCOPY_EXIT! GEQ 8 (
    echo [失败] 复制便携 Python 运行时失败，Robocopy 退出码：!ROBOCOPY_EXIT!
    goto FAILED
)

call :WRITE_VERSION "%FIRST_TARGET%\VERSION.txt" "首次部署包" "包含完整便携 Python 与 AgentScope 依赖"
if errorlevel 1 goto FAILED

echo [压缩] 正在生成日常更新包……
call :CREATE_ARCHIVE "%UPDATE_NAME%" "%UPDATE_ARCHIVE%"
if errorlevel 1 goto FAILED

echo [压缩] 正在生成首次部署包，文件较大，请耐心等待……
call :CREATE_ARCHIVE "%FIRST_NAME%" "%FIRST_ARCHIVE%"
if errorlevel 1 goto FAILED

for /f %%C in ('dir /A-D /S /B "%UPDATE_TARGET%" ^| find /C /V ""') do set "UPDATE_FILES=%%C"
for /f %%C in ('dir /A-D /S /B "%FIRST_TARGET%" ^| find /C /V ""') do set "FIRST_FILES=%%C"
for %%Z in ("%UPDATE_ARCHIVE%") do set "UPDATE_SIZE=%%~zZ"
for %%Z in ("%FIRST_ARCHIVE%") do set "FIRST_SIZE=%%~zZ"

echo.
echo [完成] Dobby 服务器更新包已生成并完成本地前端构建。
echo [首次部署] %FIRST_ARCHIVE%
echo [首次部署] 文件数：%FIRST_FILES%，字节数：%FIRST_SIZE%
echo [日常更新] %UPDATE_ARCHIVE%
echo [日常更新] 文件数：%UPDATE_FILES%，字节数：%UPDATE_SIZE%
echo.
echo 服务器第一次增加 AgentScope 时使用 dobby-server-first-install.zip。
echo 后续更新使用 dobby-server-update.zip。
echo 两个包均不包含 .env 和 data，服务器不执行 npm、pnpm 或 pip。
goto FINISH

:BUILD_PLATFORM_FRONTEND
echo [构建] 正在构建工程管理平台前端……
if exist "%ROOT%frontend\dist" rmdir /S /Q "%ROOT%frontend\dist"
pushd "%ROOT%frontend"
if not exist "node_modules" (
    call npm.cmd ci
    if errorlevel 1 (
        popd
        echo [失败] 开发机安装平台前端依赖失败。
        exit /b 1
    )
)
call npm.cmd run build
set "BUILD_EXIT=!ERRORLEVEL!"
popd
if not "!BUILD_EXIT!"=="0" (
    echo [失败] 平台前端构建失败。
    exit /b 1
)
if not exist "%ROOT%frontend\dist\index.html" (
    echo [失败] 平台前端未生成 dist\index.html。
    exit /b 1
)
exit /b 0

:BUILD_AGENTSCOPE_FRONTEND
echo [构建] 正在构建 Dobby 智能体管理端……
if exist "%ROOT%AgentScope\agentscope-web-ui\frontend\dist" rmdir /S /Q "%ROOT%AgentScope\agentscope-web-ui\frontend\dist"
pushd "%ROOT%AgentScope\agentscope-web-ui"
if not exist "node_modules\.pnpm" (
    call pnpm.cmd install --frozen-lockfile
    if errorlevel 1 (
        popd
        echo [失败] 开发机安装 Dobby 管理端依赖失败。
        exit /b 1
    )
)
call pnpm.cmd run build:frontend
set "BUILD_EXIT=!ERRORLEVEL!"
popd
if not "!BUILD_EXIT!"=="0" (
    echo [失败] Dobby 管理端构建失败。
    exit /b 1
)
if not exist "%ROOT%AgentScope\agentscope-web-ui\frontend\dist\index.html" (
    echo [失败] Dobby 管理端未生成 dist\index.html。
    exit /b 1
)
exit /b 0

:COPY_CODE_DIR
set "SOURCE_DIR=%ROOT%%~1"
set "TARGET_DIR=%UPDATE_TARGET%\%~2"
if not exist "%SOURCE_DIR%" (
    echo [失败] 缺少目录：%SOURCE_DIR%
    exit /b 1
)
robocopy "%SOURCE_DIR%" "%TARGET_DIR%" /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP /XD node_modules __pycache__ .pytest_cache .git /XF *.pyc >nul
set "ROBOCOPY_EXIT=!ERRORLEVEL!"
if !ROBOCOPY_EXIT! GEQ 8 (
    echo [失败] 复制目录失败：%SOURCE_DIR%
    echo [失败] Robocopy 退出码：!ROBOCOPY_EXIT!
    exit /b 1
)
exit /b 0

:WRITE_VERSION
(
    echo Dobby 工程管理平台 %~2
    echo.
    echo 生成时间：%DATE% %TIME%
    echo 包类型：%~2
    echo Python：%~3
    echo 前端：已在开发机完成构建
    echo 服务器 Node.js：不需要
    echo.
    echo 本包不包含服务器 .env、data\engpm.db 或 data\agentscope。
    echo 首次部署请先阅读“服务器部署说明.md”，再运行“服务器首次部署检查.bat”。
    echo 服务器统一启动命令：服务器一键启动.bat
) > "%~1"
if not exist "%~1" exit /b 1
exit /b 0

:CREATE_ARCHIVE
set "ARCHIVE_FOLDER=%~1"
set "ARCHIVE_FILE=%~2"
if exist "%ARCHIVE_FILE%" del /Q "%ARCHIVE_FILE%"
pushd "%OUTPUT_ROOT%"
"%ROOT%python-3.13.14\python.exe" -m zipfile -c "%ARCHIVE_FILE%" "%ARCHIVE_FOLDER%"
set "ZIP_EXIT=!ERRORLEVEL!"
popd
if not "!ZIP_EXIT!"=="0" (
    if exist "%ARCHIVE_FILE%" del /Q "%ARCHIVE_FILE%"
    echo [失败] 生成压缩包失败：%ARCHIVE_FILE%
    exit /b 1
)
exit /b 0

:REQUIRE_FILE
if not exist "%ROOT%%~1" (
    echo [失败] 缺少必要文件：%ROOT%%~1
    exit /b 1
)
exit /b 0

:COPY_FAILED
echo [失败] 复制更新包文件时发生错误。

:FAILED
echo.
echo Dobby 服务器更新包生成失败。
if /I not "%~1"=="--no-pause" pause
exit /b 1

:FINISH
if /I not "%~1"=="--no-pause" pause
exit /b 0
