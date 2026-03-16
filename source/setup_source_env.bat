@echo off
setlocal EnableExtensions

set "BASE=%~dp0"
set "VENV=%BASE%venv_webview"
set "PYTHON_EXE=%VENV%\Scripts\python.exe"
set "STAMP=%VENV%\.requirements_installed"
set "PY_VER="

cd /d "%BASE%"

if exist "%PYTHON_EXE%" goto detect_existing_venv

py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 goto create_venv

echo [ERROR] Python 3.12 was not found.
echo [INFO] This project's source-mode pywebview setup currently requires Python 3.12.
echo [INFO] Install Python 3.12, delete venv_webview if it already exists, then run this file again.
exit /b 1

:create_venv
echo [STEP] Creating venv_webview with Python 3.12...
py -3.12 -m venv "%VENV%"
if errorlevel 1 (
    echo [ERROR] Failed to create venv_webview.
    exit /b 1
)

goto ensure_pip

:detect_existing_venv
for /f "tokens=2" %%v in ('"%PYTHON_EXE%" -V 2^>^&1') do set "PY_VER=%%v"
if defined PY_VER set "PY_VER=%PY_VER:~0,4%"

if "%PY_VER%"=="3.12" goto ensure_pip

echo [ERROR] Existing venv_webview uses Python %PY_VER%.
echo [INFO] This project's source-mode pywebview setup currently requires Python 3.12.
echo [INFO] Install Python 3.12, delete venv_webview, then run this file again.
exit /b 1

:ensure_pip
"%PYTHON_EXE%" -m pip --version >nul 2>nul
if not errorlevel 1 goto install_requirements

echo [STEP] Restoring pip inside venv_webview...
"%PYTHON_EXE%" -m ensurepip --upgrade >nul 2>nul
"%PYTHON_EXE%" -m pip --version >nul 2>nul
if not errorlevel 1 goto install_requirements

echo [ERROR] pip is unavailable inside venv_webview.
echo [INFO] Delete venv_webview and run this file again.
exit /b 1

:install_requirements
if exist "%STAMP%" goto ready

echo [STEP] Installing dependencies from requirements.txt...
"%PYTHON_EXE%" -m pip install -r "%BASE%requirements.txt"
if errorlevel 1 (
    echo [ERROR] Dependency installation failed.
    echo [INFO] Re-run setup_source_env.bat after fixing package issues.
    exit /b 1
)

break > "%STAMP%"

:ready
echo [OK] Source environment is ready.
exit /b 0