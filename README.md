# MT5 Signal Relay

Sistem relay sinyal trading dari **MetaTrader 5 → VPS Receiver → Telegram** (via selfbot user account), dengan dashboard live di Big Guy Management System. Full Python — no EA.

## Arsitektur

```
┌──────────────────┐  POST /api/signal  ┌────────────────────┐  sb_queue.json  ┌───────────┐
│ MT5 Detector     │ ─────────────────► │ VPS Receiver       │ ──────────────► │ Selfbot   │
│ signal_detector  │  + X-Signal-Secret │ receiver.py        │                 │ selfbot.py│
│ (Python, di RDP) │                    │ HTTP 127.0.0.1:3203│                 │ (Telethon)│
└──────────────────┘                    └────────────────────┘                 └─────┬─────┘
                                     │                                     │
                                     │ GET /api/health, /api/positions     ▼
                                     └──────────────► Big Guy MS      Telegram channel
                                                      /signal-monitor (SSE)
```

- **Signal detector** (`receiver/src/signal_detector.py`) — jalan di RDP Windows, baca trade dari terminal MT5 langsung via library `MetaTrader5`: polling deals/positions/pending orders tiap 1 detik, kirim OPEN/CLOSE/SLTP/LIMIT/NOTICE. Watchdog + auto re-login + health check + remote config.
- **Receiver** (`receiver/src/receiver.py`) — terima sinyal, kelola lock/anti-duplikat, tulis `sb_queue.json`
- **Selfbot** (`receiver/src/selfbot.py`) — baca queue, kirim pesan ke Telegram via akun user (Telethon)
- **Big Guy MS** — stream SSE ke `/signal-monitor/`

## Struktur

```
receiver/
  src/receiver.py               HTTP server receiver (PORT 3203)
  src/selfbot.py                Pengirim Telegram (Telethon)
  src/signal_detector.py        Detector sinyal MT5 (Python, jalan di RDP)
  config/detector_config.example.json   Config detector (copy -> detector_config.json di VPS)
  config/config.example.json    Config detector RDP (copy -> config.json sebelah script)
  scripts/install_task.bat      Install scheduled task Windows (auto-start)
  scripts/run.bat               Jalankan receiver (foreground)
  README.md                     Panduan setup receiver
```

## Setup Cepat

### 1. Signal Detector (di RDP Windows)
1. Install dependencies: `pip install MetaTrader5 requests`
2. Copy `receiver/config/config.example.json` → `config.json` (sebelah script), isi:
   - `mt5.login` / `mt5.password` / `mt5.server` → akun MT5
   - `receiver_url` → `https://hirmes.bensserver.cloud/api/signal`
   - `secret` → sama dengan `RECEIVER_SECRET` di `.env` receiver
3. Jalankan: `python signal_detector.py` (manual) atau `install_task.bat` (auto-start saat logon RDP)

### 2. Receiver (di VPS)
```bash
cd receiver
cp config/detector_config.example.json detector_config.json
# buat .env
cat > .env << 'EOF'
RECEIVER_SECRET=isi-secret-kamu
PORT=3203
EOF
python src/receiver.py   # stdlib murni, tidak ada dep eksternal
```

### 3. Selfbot (di VPS / tempat lain)
```bash
cd receiver
pip install telethon
# edit src/selfbot.py — API_ID, API_HASH, TG_CHAT_ID sesuai akun kamu
python src/selfbot.py
```

### 4. Dashboard
Big Guy MS `/signal-monitor/` men-stream dari receiver via `/api/health` + SSE.

## API Receiver

| Endpoint | Method | Deskripsi |
|---|---|---|
| `/api/signal` | POST | Terima sinyal dari detector (X-Signal-Secret) |
| `/api/health` | GET | Status, statistik queue/lock |
| `/api/positions` | GET | Daftar posisi aktif |
| `/api/logs` | GET | Log terakhir |
| `/api/config/detector` | GET/POST | Baca/tulis config detector (auth) |
| `/api/config/detector/checksum` | GET | Checksum config (untuk polling detector) |
| `/api/reset` | POST | Reset system (safety check posisi aktif) |

## Format Sinyal

```json
{ "action": "OPEN", "symbol": "XAUUSD", "type": "BUY", "lot": 0.5,
  "price": 4820.0, "sl": 4815.0, "tp": 4835.0, "digits": 2,
  "magic": 0, "deal": 123, "position": 456 }
```

Actions: `OPEN`, `CLOSE`, `SLTP`, `LIMIT`, `NOTICE`.

## Panduan Lengkap

- Setup RDP / receiver / detector: `receiver/README.md`
