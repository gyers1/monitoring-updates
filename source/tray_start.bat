@echo off
setlocal EnableExtensions

set "BASE=%~dp0"
set "CHECK_ONLY="
set "SOURCE_PY="
set "RELEASE_DIR=%BASE%..\release"
set "RELEASE_START=%RELEASE_DIR%\start_tray.bat"
set "RELEASE_EXE=%RELEASE_DIR%\MonitoringDashboard.exe"

if /I "%~1"=="--check-only" set "CHECK_ONLY=1"

cd /d "%BASE%"

if defined CHECK_ONLY goto verbose_setup
call "%BASE%setup_source_env.bat" >nul 2>&1
goto setup_done

:verbose_setup
call "%BASE%setup_source_env.bat"

:setup_done
if errorlevel 1 goto fallback_release

if exist "%BASE%venv_webview\Scripts\pythonw.exe" set "SOURCE_PY=%BASE%venv_webview\Scripts\pythonw.exe"
if not defined SOURCE_PY if exist "%BASE%venv\Scripts\pythonw.exe" set "SOURCE_PY=%BASE%venv\Scripts\pythonw.exe"
if not defined SOURCE_PY if exist "%BASE%.venv\Scripts\pythonw.exe" set "SOURCE_PY=%BASE%.venv\Scripts\pythonw.exe"
if not defined SOURCE_PY if exist "%BASE%venv_webview\Scripts\python.exe" set "SOURCE_PY=%BASE%venv_webview\Scripts\python.exe"
if not defined SOURCE_PY if exist "%BASE%venv\Scripts\python.exe" set "SOURCE_PY=%BASE%venv\Scripts\python.exe"
if not defined SOURCE_PY if exist "%BASE%.venv\Scripts\python.exe" set "SOURCE_PY=%BASE%.venv\Scripts\python.exe"

if defined SOURCE_PY goto run_source

echo [ERROR] Python launcher not found after environment setup.
exit /b 1

:run_source
if defined CHECK_ONLY goto report_source
start "" /D "%BASE%" "%SOURCE_PY%" "%BASE%webview_app.py"
exit /b 0

:report_source
echo [OK] Source launcher: %SOURCE_PY%
exit /b 0

:fallback_release
if exist "%RELEASE_START%" goto run_release_start
if exist "%RELEASE_EXE%" goto run_release_exe

echo [ERROR] Source environment setup failed and NEW\release fallback is missing.
exit /b 1

:run_release_start
if defined CHECK_ONLY goto report_release_start
echo [WARN] Source environment unavailable. Starting NEW\release.
start "" /D "%RELEASE_DIR%" "%RELEASE_START%"
exit /b 0

:report_release_start
echo [OK] Fallback release launcher: %RELEASE_START%
exit /b 0

:run_release_exe
if defined CHECK_ONLY goto report_release_exe
echo [WARN] Source environment unavailable. Starting NEW\release executable.
start "" /D "%RELEASE_DIR%" "%RELEASE_EXE%"
exit /b 0

:report_release_exe
echo [OK] Fallback release executable: %RELEASE_EXE%
exit /b 0
