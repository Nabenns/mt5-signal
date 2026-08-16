# MT5 Signal Detector for RDP Windows (FULL PYTHON)

## 🎯 What This Is

**Full Python replacement for the EA-based solution.**  
No EA needed — just run this script on your RDP and you're good.

### Features
- ✅ **Auto-login** via API (`mt5.initialize()`)
- ✅ **Watchdog**: if MT5 terminal closes → auto-relaunch + re-login
- ✅ **Health checker**: monitors connection, tick freshness, VPS status
- ✅ **Signal relay**: sends OPEN/SLTP/CLOSE to your VPS receiver (same format as EA)
- ✅ **System notices**: e.g., "MT5 restarted", "VPS down" sent to Telegram
- ✅ **Deduplication**: avoids double-sending same deal/position

## 📁 Files in This Folder

| File | Description |
|------|-------------|
| `signal_detector.py` | Main script (run this one) |
| `config.example.json` | Template — copy to `config.json` and edit |
| `run.bat` | Double-click to start (manual mode) |
| `install_task.bat` | Create scheduled task at user logon (auto-start) |
| `README.md` | This file |

## 🚀 Quick Start

### Step 1: Install Dependencies
```powershell
# In PowerShell or CMD on RDP
pip install MetaTrader5 requests
```

### Step 2: Configure
```powershell
copy config.example.json config.json
# EDIT config.json:
#   - login: your MT5 account number
#   - password: your MT5 password
#   - server: broker server name (e.g., "Broker-Demo")
#   - receiver_url: https://hirmes.bensserver.cloud/api/signal
#   - secret: paste RECEIVER_SECRET from .env on VPS
```

### Step 3: Run It

**Option A: Manual run (for testing)**
```powershell
python signal_detector.py
# Or double-click run.bat
```

**Option B: Auto-start at logon (recommended)**
```powershell
Install-task.bat
# Runs automatically when you log into RDP
```

**Verify it's running:**
```powershell
schtasks /query /tn "MT5 Signal Detector"
```

## 🔍 How It Works

1. **Detects new trades** by polling `history_deals_get()` every 1 second.
2. **Sends signals** to your VPS receiver (format: same as EA) → selfbot → Telegram.
3. **Monitors health** (terminal, broker ping, ticks, VPS reachability).
4. **Auto-recovers** if MT5 crashes/restarts.
5. **Sends system notices** to Telegram (e.g., "watchdog restarted MT5").

## ⚙️ Configuration Options

In `config.json`:

| Field | Example | Description |
|-------|---------|-------------|
| `login` | 12345678 | Your MT5 account |
| `password` | "yourpass" | Password |
| `server` | "Broker-SERVER" | Broker server name |
| `terminal_path` | `"C:\\Program Files\\MetaTrader 5\\terminal64.exe"` | Full path (optional) |
| `receiver_url` | `"https://hirmes.bensserver.cloud/api/signal"` | HTTP endpoint on VPS |
| `secret` | "***..."*** | RECEIVER_SECRET from VPS `.env` |
| `poll_interval` | 1.0 | Seconds between polls (default: 1s) |
| `health_interval` | 60 | Seconds between health checks |
| `startup_seed_minutes` | 5 | Ignore deals older than X min at startup (avoid duplicates) |
| `notify_restart` | true | Send Telegram notice when MT5 auto-restarted |

## 🐛 Troubleshooting

### ❌ "MetaTrader5 library not found"
```powershell
pip install MetaTrader5 requests
```

### ❌ "initialize() failed: Error code 155"
- Check if MT5 Terminal is already open & logged in. If yes, close it first.
- Then run detector again (it will connect).

### ❌ "VPS unreachable"
- Verify receiver URL & secret are correct.
- Test manually: `curl "https://hirmes.bensserver.cloud/api/health?secret=<SECRET>"`

### ❌ "Duplicate signals detected"
- Increase `startup_seed_minutes` from 5 to 10–15 minutes.

## 📊 Output

- `detector.log` – logs all events (connection, signals, health)
- `health.json` – latest health snapshot (readable JSON)
- Telegram channel – receives trade signals + system notices

## 🔄 Migration from EA

If you're currently using `SignalRelay.mq5` on RDP:

1. Install dependencies: `pip install MetaTrader5 requests`
2. Copy `config.example.json` → `config.json`, fill credentials
3. Remove `SignalRelay.mq5` from MT5 (no longer needed!)
4. Run `install_task.bat` (or `python signal_detector.py`)
5. Done! The Python script replaces the EA entirely.

---

**GitHub Repo:** https://github.com/Nabenns/mt5-signal  
**Receiver/VPS:** hirmes.bensserver.cloud (same backend as EA version)
