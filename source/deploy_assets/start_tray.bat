@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "BASE=%~dp0"
set "EXE=%BASE%MonitoringDashboard.exe"
set "PYWEBVIEW_GUI=edgechromium"
set "ENV_FILE=%BASE%.env"
set "SETTINGS_FILE=%BASE%_internal\config\settings.py"

rem Normalize .env before app startup.
rem 1) remove UTF-8 BOM
rem 2) normalize legacy update_url key casing
rem 3) if legacy settings.py (no update_url/extra-ignore), drop UPDATE_URL to avoid ValidationError crash
if exist "%ENV_FILE%" (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='%ENV_FILE%'; $s='%SETTINGS_FILE%'; $t=[System.IO.File]::ReadAllText($p,[System.Text.Encoding]::UTF8); if($t.Length -gt 0 -and [int][char]$t[0] -eq 65279){$t=$t.Substring(1)}; $legacy=$false; if(Test-Path $s){ $st=[System.IO.File]::ReadAllText($s,[System.Text.Encoding]::UTF8); if(($st -notmatch '(?m)^\s*update_url\s*:') -and ($st -notmatch 'extra\s*=\s*\""ignore\""')){$legacy=$true} }; $t=[Regex]::Replace($t,'(?im)^\s*update_url\s*=','UPDATE_URL='); if($legacy){$t=[Regex]::Replace($t,'(?im)^\s*UPDATE_URL\s*=.*(\r?\n)?','')}; [System.IO.File]::WriteAllText($p,$t,[System.Text.UTF8Encoding]::new($false))" >nul 2>nul
)

rem Clear downloaded-file mark (Zone.Identifier) to prevent silent block issues.
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%BASE%' -Recurse -File | Unblock-File" >nul 2>nul

rem Ensure selector helper injection file exists at runtime path expected by webview_app.
set "HELPER_SRC=%BASE%_internal\presentation\static\selector_helper_inject.js"
set "HELPER_DIR=%BASE%presentation\static"
set "HELPER_DST=%HELPER_DIR%\selector_helper_inject.js"
if exist "%HELPER_SRC%" (
    if not exist "%HELPER_DIR%" mkdir "%HELPER_DIR%" >nul 2>nul
    copy /Y "%HELPER_SRC%" "%HELPER_DST%" >nul 2>nul
)

rem Ensure preview download guard exists for in-app preview window.
set "PREVIEW_SRC=%BASE%_internal\presentation\static\preview_download_guard.js"
set "PREVIEW_DIR=%BASE%presentation\static"
set "PREVIEW_DST=%PREVIEW_DIR%\preview_download_guard.js"
if exist "%PREVIEW_SRC%" (
    if not exist "%PREVIEW_DIR%" mkdir "%PREVIEW_DIR%" >nul 2>nul
    copy /Y "%PREVIEW_SRC%" "%PREVIEW_DST%" >nul 2>nul
)

if not exist "!EXE!" (
    echo [ERROR] MonitoringDashboard.exe not found.
    echo [INFO] Keep start_tray.bat in the same folder as MonitoringDashboard.exe.
    pause
    exit /b 1
)

rem Kill stale/orphan process first (prevents false "already running" state).
taskkill /F /IM MonitoringDashboard.exe >nul 2>nul

start "" /D "!BASE!" "!EXE!"
timeout /t 2 >nul

rem Verify exact executable path is running (prevents stale process from another folder).
powershell -NoProfile -ExecutionPolicy Bypass -Command "$target=[System.IO.Path]::GetFullPath('!EXE!').ToLowerInvariant(); $ok=$false; Get-CimInstance Win32_Process -Filter \"name='MonitoringDashboard.exe'\" | ForEach-Object { if($_.ExecutablePath){ if([System.IO.Path]::GetFullPath($_.ExecutablePath).ToLowerInvariant() -eq $target){$ok=$true} } }; if($ok){ exit 0 } else { exit 1 }" >nul 2>nul
if errorlevel 1 (
    rem 1-time hard retry
    taskkill /F /IM MonitoringDashboard.exe >nul 2>nul
    timeout /t 1 >nul
    start "" /D "!BASE!" "!EXE!"
    timeout /t 2 >nul
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$target=[System.IO.Path]::GetFullPath('!EXE!').ToLowerInvariant(); $ok=$false; Get-CimInstance Win32_Process -Filter \"name='MonitoringDashboard.exe'\" | ForEach-Object { if($_.ExecutablePath){ if([System.IO.Path]::GetFullPath($_.ExecutablePath).ToLowerInvariant() -eq $target){$ok=$true} } }; if($ok){ exit 0 } else { exit 1 }" >nul 2>nul
    if errorlevel 1 (
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.Windows.Forms;[System.Windows.Forms.MessageBox]::Show('Startup failed. Check startup.log in the same folder.','Monitoring Dashboard',[System.Windows.Forms.MessageBoxButtons]::OK,[System.Windows.Forms.MessageBoxIcon]::Error)" >nul 2>nul
        if exist "!BASE!startup.log" start "" notepad "!BASE!startup.log"
        exit /b 1
    )
)

exit /b 0