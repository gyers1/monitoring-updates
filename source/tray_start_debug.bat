@echo off
setlocal EnableExtensions

set "BASE=%~dp0"
set "CHECK_ONLY="
set "PYC="

if /I "%~1"=="--check-only" set "CHECK_ONLY=1"

cd /d "%BASE%"

call "%BASE%setup_source_env.bat"
if errorlevel 1 goto setup_failed

if exist "%BASE%venv_webview\Scripts\python.exe" set "PYC=%BASE%venv_webview\Scripts\python.exe"
if not defined PYC if exist "%BASE%venv\Scripts\python.exe" set "PYC=%BASE%venv\Scripts\python.exe"
if not defined PYC if exist "%BASE%.venv\Scripts\python.exe" set "PYC=%BASE%.venv\Scripts\python.exe"

if defined PYC goto debug_ready

echo [ERROR] python.exe not found after environment setup.
pause
exit /b 1

:setup_failed
pause
exit /b 1

:debug_ready
if defined CHECK_ONLY goto report_debug
"%PYC%" "%BASE%webview_app.py"
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" goto debug_done

echo [ERROR] webview_app.py exited with code %RC%.

:debug_done
pause
exit /b %RC%

:report_debug
echo [OK] Debug launcher: %PYC%
exit /b 0
