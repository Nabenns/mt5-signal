@echo off
title MT5 Signal Detector - Install as Scheduled Task (Auto-start at logon)

chcp 65001 > nul

cd /d "%~dp0"

:: Check if config exists
if not exist "config.json" (
    echo ❌ config.json not found! Run run.bat first and edit it.
    pause
    exit /b
)

:: Find Python path
for /f "tokens=* usebackq" %%p in (`where python`) do (
    set PYTHON_PATH=%%p
    goto :found_python
)
echo ❌ Python not found in PATH
pause
exit /b

:found_python

:: Create the scheduled task to run at user logon
schtasks /create /tn "MT5 Signal Detector" /tr "pythonw \"%~dp0signal_detector.py\"" /sc onlogon /rl highest /f

if %errorlevel% equ 0 (
    echo ✅ Task "MT5 Signal Detector" created successfully!
    echo    Will auto-start when you log into RDP.
    echo.
    echo 📋 To verify:
    echo    schtasks /query /tn "MT5 Signal Detector"
    echo.
    echo 📋 To delete:
    echo    schtasks /delete /tn "MT5 Signal Detector" /f
) else (
    echo ❌ Failed to create task. Try running as Administrator.
)

pause
