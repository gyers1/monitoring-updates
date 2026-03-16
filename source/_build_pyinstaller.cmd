@echo off
setlocal EnableExtensions
set "BASE=%~dp0"
echo [INFO] _build_pyinstaller.cmd is deprecated.
echo [INFO] Use build_release.bat -Version vYYYYMMDDHHMM instead.
call "%BASE%build_release.bat" %*
exit /b %ERRORLEVEL%