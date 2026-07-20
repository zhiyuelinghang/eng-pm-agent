@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
set "SOURCE=%ROOT%backend"
set "OUTPUT_ROOT=%ROOT%更新文件\后端更新"
set "TARGET=%OUTPUT_ROOT%\backend"
set "ARCHIVE=%ROOT%更新文件\后端更新.zip"

title 生成后端更新文件

if not exist "%SOURCE%\app\main.py" (
  echo [失败] 未找到后端目录：
  echo %SOURCE%
  goto FAILED
)

where tar.exe >nul 2>nul
if errorlevel 1 (
  echo [失败] 当前系统未找到 tar.exe，无法生成 zip 压缩包。
  goto FAILED
)

echo 正在生成后端更新文件夹...
echo 来源：%SOURCE%
echo 输出：%TARGET%
echo.

if not exist "%TARGET%" mkdir "%TARGET%" >nul 2>nul

robocopy "%SOURCE%" "%TARGET%" /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
set "ROBOCOPY_EXIT=%ERRORLEVEL%"

if %ROBOCOPY_EXIT% GEQ 8 (
  echo.
  echo [失败] 复制后端文件时发生错误，Robocopy 退出码：%ROBOCOPY_EXIT%
  goto FAILED
)

echo 正在压缩后端更新文件...
if exist "%ARCHIVE%" del /q "%ARCHIVE%"
pushd "%OUTPUT_ROOT%"
tar.exe -a -c -f "%ARCHIVE%" backend
set "TAR_EXIT=%ERRORLEVEL%"
popd

if not "%TAR_EXIT%"=="0" (
  if exist "%ARCHIVE%" del /q "%ARCHIVE%"
  echo.
  echo [失败] 生成后端 zip 压缩包时发生错误。
  goto FAILED
)

for /f %%C in ('dir /a-d /s /b "%TARGET%" ^| find /c /v ""') do set "FILE_COUNT=%%C"

echo.
echo [完成] 后端更新文件已生成，共 %FILE_COUNT% 个文件。
echo [完成] 压缩包：%ARCHIVE%
echo.
echo 服务器更新方法：
echo 将“%OUTPUT_ROOT%”中的 backend 文件夹复制到服务器项目根目录，覆盖服务器原 backend 文件夹。
echo backend 中的全部文件均已复制。
echo 不会影响项目根目录的 .env、data 和 python-3.13.14。
echo 覆盖完成后重新运行 start-frontend.bat。
echo.
echo 输出位置：%OUTPUT_ROOT%
echo 压缩包位置：%ARCHIVE%
goto FINISH

:FAILED
echo.
echo 后端更新文件生成失败。
if /I not "%~1"=="--no-pause" pause
exit /b 1

:FINISH
if /I not "%~1"=="--no-pause" pause
exit /b 0
