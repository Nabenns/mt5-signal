@echo off
REM Jalankan detektor instance kedua (akun VIP) — config terpisah.
REM 1. Copy config.example.json jadi config_vip.json, isi:
REM    - mt5.login/password/server akun VIP
REM    - "source": "vip"
REM 2. Double-click file ini (atau install scheduled task via install_task.bat VIP)
cd /d %~dp0..
python src\signal_detector.py --config config_vip.json
pause
