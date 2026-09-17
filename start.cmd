@echo off
rem ============================================================
rem  WorkBuddy Token Usage Dashboard - Windows launcher
rem
rem  用法：双击本文件，或在命令行传参：
rem      start.cmd --port 8800 --open
rem      start.cmd --rebuild          忽略缓存全量重扫
rem ============================================================
setlocal
cd /d "%~dp0"

set "PYEXE="
where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE ( where py >nul 2>&1 && set "PYEXE=py" )
if not defined PYEXE (
  echo [x] 找不到 Python。请安装 Python 3.8+ 并确保它在 PATH 中。
  pause
  exit /b 1
)

"%PYEXE%" "%~dp0usage_server.py" %*
exit /b %ERRORLEVEL%
