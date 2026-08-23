@echo off
REM Install scheduled task to auto-start receiver on boot
cd /d %~dp0..
set TASK_NAME=MT5SignalReceiver
schtasks /create /tn %TASK_NAME% /tr "\"%~dp0..\run.bat\"" /sc onlogon /rl highest /f
echo Task installed: %TASK_NAME%
echo Note: run.bat must be in receiver/scripts/ or adjust path.
pause
