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
  src/receiver.py               HTTP server receiver (PORT 3203) — v13, multi akun/multi channel
  src/selfbot.py                Pengirim Telegram (Telethon) — v11, 1 client per akun + template format
  src/signal_detector.py        Detector sinyal MT5 (Python, jalan di RDP) — 1 script, N instance (--config)
  src/login.py                  Login akun Telegram baru (OTP + 2FA) → telegram_config.json
  config/detector_config.example.json   Template config detector (dikelola via API, per source)
  config/config.example.json    Template config instance detector di RDP (source/test/portable)
  config/telegram_config.example.json   Template accounts + routes
  scripts/run.bat               Jalankan receiver (foreground)
  scripts/run_vip.bat           Jalankan instance detector kedua (--config config_vip.json)
  scripts/install_task.bat      Install scheduled task Windows (auto-start)
  README.md                     Panduan setup receiver/detector
setup.sh                        Cek service + route PROD/TEST/VIP + panduan RDP
BIGGUY-MONITORING.md            Panduan read-only buat AI Big Guy MS (monitoring)
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

Catatan produksi: receiver + selfbot jalan sebagai service systemd (`mt5-signal-receiver`,
`mt5-signal-selfbot`) di `/root/mt5-signal/` dengan layout FLAT (file langsung di root,
bukan `src/`). Path BASE receiver adaptif (deteksi folder `src/`), jadi kode yang sama
jalan di dua layout — jangan diubah jadi hardcoded.

### 3. Selfbot (di VPS / tempat lain)
```bash
cd receiver
pip install telethon
# akun + channel dikelola lewat telegram_config.json (lihat bagian Multi Akun di bawah)
python src/selfbot.py
```

### 4. Dashboard
Big Guy MS `/signal-monitor/` men-stream dari receiver via `/api/health` + SSE.

## API Receiver

| Endpoint | Method | Auth | Deskripsi |
|---|---|---|---|
| `/api/signal` | POST | ya | Terima sinyal dari detector (X-Signal-Secret) |
| `/api/health` | GET | tidak | Status, statistik queue/lock |
| `/api/positions` | GET | tidak | Daftar posisi aktif (lock) — output menyertakan `source` |
| `/api/logs` | GET | tidak | 100 log terakhir (param limit diabaikan) |
| `/api/config/detector[?source=&mask=1]` | GET/POST | ya | Baca/tulis config detector (per source) |
| `/api/config/detector/checksum[?source=]` | GET | tidak | Checksum config (dipoll detector tiap 30s) |
| `/api/config/telegram[?mask=1]` | GET/POST | ya | Baca/tulis accounts + routes |
| `/api/config/telegram/checksum` | GET | tidak | Checksum telegram config (selfbot hot-reload) |
| `/api/reset` | POST | ya | Reset system (`?force=true` buat lewati safety lock) |

Catatan: `source` pada config detector = instance detector (mis. `vip` → file `detector_config_vip.json`).
`/api/state` **tidak ada di receiver** (dipakai sebagian konsumen dashboard — lihat BIGGUY-MONITORING.md).


## Format Sinyal

```json
{ "action": "OPEN", "symbol": "XAUUSD", "type": "BUY", "lot": 0.5,
  "price": 4820.0, "sl": 4815.0, "tp": 4835.0, "digits": 2,
  "magic": 0, "deal": 123, "position": 456 }
```

Actions: `OPEN`, `CLOSE`, `SLTP`, `LIMIT`, `NOTICE`.

## Panduan Lengkap

- Setup RDP / receiver / detector: `receiver/README.md`
