@echo off
cd /d %~dp0..
echo Starting MT5 Signal Receiver...
python src\receiver.py
pause
