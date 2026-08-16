@echo off
title MT5 Signal Detector (Run at startup)

chcp 65001 > nul

cd /d "%~dp0"

:: Cek Python install
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python belum install di RDP lo!
    echo   Download: https://www.python.org/downloads/
    pause
    exit /b
)

:: Cek MetaTrader5 library
python -c "import MetaTrader5; print('MetaTrader5 OK')" 2>nul
if %errorlevel% neq 0 (
    echo 📦 Install MetaTrader5...
    pip install MetaTrader5 requests
)

:: Copy config contoh ke real config kalau belum ada
if not exist "config.json" (
    echo 📄 Copy config.example.json -> config.json
    copy config.example.json config.json >nul
    echo ✅ EDIT config.json: isin credentials lo!
    echo    login, password, server, secret
    pause
)

:: Jalankan
echo 🔥 STARTING DETECTOR...
python signal_detector.py

pause
