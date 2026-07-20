@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0"
set "SOURCE=%ROOT%frontend"
set "OUTPUT_ROOT=%ROOT%更新文件\前端更新"
set "TARGET=%OUTPUT_ROOT%\frontend"
set "ARCHIVE=%ROOT%更新文件\前端更新.zip"

title 生成前端更新文件

if not exist "%SOURCE%\package.json" (
  echo [失败] 未找到前端目录：
  echo %SOURCE%
  goto FAILED
)

where tar.exe >nul 2>nul
if errorlevel 1 (
  echo [失败] 当前系统未找到 tar.exe，无法生成 zip 压缩包。
  goto FAILED
)

echo 正在生成前端更新文件夹...
echo 来源：%SOURCE%
echo 输出：%TARGET%
echo.

if not exist "%TARGET%" mkdir "%TARGET%" >nul 2>nul

robocopy "%SOURCE%" "%TARGET%" /MIR /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
set "ROBOCOPY_EXIT=%ERRORLEVEL%"

if %ROBOCOPY_EXIT% GEQ 8 (
  echo.
  echo [失败] 复制前端文件时发生错误，Robocopy 退出码：%ROBOCOPY_EXIT%
  goto FAILED
)

echo 正在压缩前端更新文件...
if exist "%ARCHIVE%" del /q "%ARCHIVE%"
pushd "%OUTPUT_ROOT%"
tar.exe -a -c -f "%ARCHIVE%" frontend
set "TAR_EXIT=%ERRORLEVEL%"
popd

if not "%TAR_EXIT%"=="0" (
  if exist "%ARCHIVE%" del /q "%ARCHIVE%"
  echo.
  echo [失败] 生成前端 zip 压缩包时发生错误。
  goto FAILED
)

for /f %%C in ('dir /a-d /s /b "%TARGET%" ^| find /c /v ""') do set "FILE_COUNT=%%C"

echo.
echo [完成] 前端更新文件已生成，共 %FILE_COUNT% 个文件。
echo [完成] 压缩包：%ARCHIVE%
echo.
echo 服务器更新方法：
echo 将“%OUTPUT_ROOT%”中的 frontend 文件夹复制到服务器项目根目录，覆盖服务器原 frontend 文件夹。
echo frontend 中的全部文件均已复制，包括 node_modules 和 dist。
echo.
echo 输出位置：%OUTPUT_ROOT%
echo 压缩包位置：%ARCHIVE%
goto FINISH

:FAILED
echo.
echo 前端更新文件生成失败。
if /I not "%~1"=="--no-pause" pause
exit /b 1

:FINISH
if /I not "%~1"=="--no-pause" pause
exit /b 0
