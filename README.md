# MT5 Signal Relay

Sistem relay sinyal trading dari **MetaTrader 5 → VPS Receiver → Telegram** (via selfbot user account), dengan dashboard live di Big Guy Management System.

## Arsitektur

```
┌─────────────┐   WebRequest    ┌──────────────────┐   sb_queue.json   ┌───────────┐
│ MT5 EA      │ ──────────────► │ VPS Receiver      │ ────────────────► │ Selfbot   │
│ SignalRelay │  POST /signal   │ receiver.py       │                   │ selfbot.py│
│ (EA di MT5) │  + X-Signal-Secret │ HTTP 127.0.0.1:3203 │                │ (Telethon)│
└─────────────┘                └──────────────────┘                   └─────┬─────┘
                                     │                                     │
                                     │ GET /api/health, /api/positions     ▼
                                     └──────────────► Big Guy MS      Telegram channel
                                                      /signal-monitor (SSE)
```

- **MT5 EA** (`mt5/ea/SignalRelay.mq5`) — deteksi posisi buka/tutup, kirim OPEN/CLOSE/SLTP/LIMIT
- **Receiver** (`receiver/src/receiver.py`) — terima sinyal, kelola lock/anti-duplikat, tulis `sb_queue.json`
- **Selfbot** (`receiver/src/selfbot.py`) — baca queue, kirim pesan ke Telegram via akun user (Telethon)
- **Signal detector** (`receiver/src/signal_detector.py`) — opsi tambahan deteksi order via terminal MT5 (RDP)
- **Big Guy MS** — stream SSE ke `/signal-monitor/`

## Struktur

```
mt5/ea/SignalRelay.mq5          EA utama (copy ke MT5 -> Experts)
receiver/
  src/receiver.py               HTTP server receiver (PORT 3203)
  src/selfbot.py                Pengirim Telegram (Telethon)
  src/signal_detector.py        Detector order MT5 (optional, via terminal)
  config/detector_config.example.json   Config detector (copy -> detector_config.json)
  config/config.example.json    Config sinyal (optional)
  scripts/install_task.bat      Install scheduled task Windows (auto-start)
  scripts/run.bat               Jalankan receiver (foreground)
  README.md                     Panduan setup receiver
```

## Setup Cepat

### 1. MT5 EA
1. Copy `mt5/ea/SignalRelay.mq5` ke folder **MQL5/Experts** terminal MT5
2. Buka MT5 → **Tools → Options → Expert Advisors** → centang **Allow WebRequest for listed URL**
3. Tambahkan URL receiver (mis. `https://vps-anda.com`) ke list whitelist
4. Attach EA ke chart. Set input:
   - `InpReceiverURL` → `https://vps-anda.com/api/signal`
   - `InpReceiverSecret` → secret yang sama dengan `.env` receiver

### 2. Receiver (di VPS)
```bash
cd receiver
cp config/detector_config.example.json detector_config.json
# buat .env
cat > .env << 'EOF'
RECEIVER_SECRET=isi-secret-kamu
PORT=3203
EOF
pip install -r requirements.txt   # tidak ada dep eksternal — stdlib murni
python src/receiver.py
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
| `/api/signal` | POST | Terima sinyal EA (X-Signal-Secret) |
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
- Konfigurasi EA: input parameters di bagian atas `SignalRelay.mq5`
