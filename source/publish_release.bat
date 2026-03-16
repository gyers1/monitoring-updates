@echo off
setlocal EnableExtensions
set "BASE=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%BASE%publish_release.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" pause
exit /b %RC%