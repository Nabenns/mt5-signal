# MT5 Signal Detector for RDP Windows (FULL PYTHON)

## 🎯 What This Is

**Full Python signal detector.**
Just run this script on your RDP and you're good.

### Features
- ✅ **Auto-login** via API (`mt5.initialize()`)
- ✅ **Watchdog**: if MT5 terminal closes → auto-relaunch + re-login
- ✅ **Health checker**: monitors connection, tick freshness, VPS status
- ✅ **Signal relay**: sends OPEN/SLTP/CLOSE to your VPS receiver (plain JSON over HTTPS)
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
2. **Sends signals** to your VPS receiver → selfbot → Telegram.
3. **Monitors health** (terminal, broker ping, ticks, VPS reachability).
4. **Auto-recovers** if MT5 crashes/restarts.
5. **Sends system notices** to Telegram (e.g., "watchdog restarted MT5").

## ⚙️ Configuration Options

In `config.json` (instance detector di RDP):

| Field | Example | Description |
|-------|---------|-------------|
| `login` | 12345678 | Akun MT5 instance ini |
| `password` | `"yourpass"` | Password |
| `server` | `"Broker-SERVER"` | Nama server broker |
| `terminal_path` | `"C:\\Program Files\\MetaTrader 5\\terminal64.exe"` | Full path terminal instance ini |
| `portable` | `true` | WAJIB true kalau ada >1 terminal MT5 di satu box (data folder terpisah) |
| `source` | `""` / `"vip"` | Identitas instance → menentukan route tujuan (jangan ketimpa remote) |
| `test` | `false` | `true` = SEMUA sinyal instance ini ke channel test (dipakai saat uji akun baru) |
| `receiver_url` | `"https://hirmes.bensserver.cloud/api/signal"` | HTTP endpoint receiver |
| `secret` | `"***..."` | RECEIVER_SECRET dari `.env` VPS |
| `poll_interval` | 1.0 | Detik antar poll (default 1s) |
| `health_interval` | 60 | Detik antar health check |
| `startup_seed_minutes` | 5 | Abaikan deal lebih tua dari X menit saat start (anti duplikat) |
| `notify_restart` | true | Kirim notice Telegram saat MT5 auto-restart |

Field `mt5.*`, `settings.*` bisa dikelola dari VPS (`/api/config/detector`); `source`,
`test`, `receiver_url`, `secret`, `portable` adalah identitas lokal instance dan
**tidak pernah** ditimpa oleh pull config remote.


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

## 👥 Multi Akun & Multi Channel (Telegram)

Selfbot v11 + receiver mendukung **banyak akun Telegram** dan **banyak channel tujuan** — semua dikelola lewat `telegram_config.json` di VPS (sebelah `receiver.py`), tanpa restart service.

### Struktur config

```json
{
  "accounts": [
    {"name": "akun-utama",  "session": "6285196827787", "api_id": 123, "api_hash": "...", "enabled": true, "default": true},
    {"name": "akun-cadangan", "session": "tg_akun_cadangan", "api_id": 123, "api_hash": "...", "enabled": false}
  ],
  "routes": [
    {"name": "prod",  "chat_id": -1001816822545, "enabled": true},
    {"name": "grup-vip", "chat_id": -1001234567890, "account": "akun-cadangan", "enabled": false},
    {"name": "test",  "chat_id": -1004479253024, "test": true, "enabled": true}
  ]
}
```

- **accounts** — tiap akun = satu session Telethon (`login.py` yang bikin). `default: true` = akun pengirim utama.
- **routes** — channel tujuan. Route `test: true` cuma kepakai kalau sinyal bawa flag `test` (proteksi nyasar tetap berlaku). `account` = pin akun pengirim (opsional). Sinyal non-test di-**fanout ke semua route non-test** yang enabled **dengan `source` yang sama** (route tanpa `source` = `public`; source non-public tanpa route = DIBUANG, anti-bocor).
- Field route opsional lain: `topic_id` (kirim sebagai reply ke topik forum), `format` (template pesan — lihat tabel di bawah).
- Tanpa config file → perilaku lama (1 akun legacy, PROD/TEST hardcode).

### Template format pesan (`format` per route)

| `format` | Dipakai untuk | Isi pesan |
|---|---|---|
| (kosong) / `default` | channel publik | `💰 BUY NOW SYMBOL \| zona`, SL bold, `TP 1/2/3 : ⁉️` |
| `vip` | VIP For Brother (topik) | sama seperti default + penutup 2 baris `JAGA RISK KALIAN GUYS ‼️` / `50 PIPS SET BE OR PARTIAL ✔️` |
| `run50` | crazypauls | badge custom 🔤🔤, TP 2 baris, penutup `RUN 50 PIPS SET BE, JAGA RISK MANAGEMENT ‼️` |
| `indi` | indicatorisme | badge custom 📈/📉, `TP : 60 PIPS` (tanpa nomor), penutup `JANGAN LUPA ATUR RISK MANAGEMENT ‼️` |

Semua template LIMIT pakai varian yang sama; SL otomatis 60 pips dari harga kalau SL dari MT5 kosong.
Offset entity dihitung dalam unit UTF-16 (`_u16`) — jangan diganti index Python biasa,
emoji astral bikin bold/emoji custom geser dan di-strip server Telegram.


### Kelola via API (tanpa SSH)

```bash
# Baca (password/api_hash di-mask)
curl -H "X-Signal-Secret: $SECRET" "https://hirmes.bensserver.cloud/api/config/telegram?mask=1"

# Update (replace accounts/routes, divalidasi: nama unik, pin akun harus ada)
curl -X POST -H "X-Signal-Secret: $SECRET" -H "Content-Type: application/json" \
  -d '{"routes":[...]}' "https://hirmes.bensserver.cloud/api/config/telegram"

# Cek version/checksum (buat polling)
curl "https://hirmes.bensserver.cloud/api/config/telegram/checksum"
```

Selfbot hot-reload dalam ≤5 detik setelah file berubah (akun baru konek, akun dihapus disconnect). Status akun live: `selfbot_health.json`.

### Login akun baru

```bash
python3 login.py                # lihat status semua akun
python3 login.py akun-baru +6281234567890   # buat akun baru (OTP via terminal)
```

### Failover

Kalau akut pengirim kena FloodWait (atau error), selfbot otomatis coba akun enabled berikutnya (urutan: pin route → akun default → sisanya). Item gagal tetap di queue dan dicoba lagi di flush berikutnya.

## 🔌 Multi Akun MT5 (2 detector, 2 channel)

Satu script, banyak instance — tiap akun MT5 satu config. Contoh setup 2 akun:

| Instance | Config | Source | Route tujuan |
|----------|--------|--------|--------------|
| Akun A (publik) | `config.json` | `""` (public) | route `prod` |
| Akun B (VIP) | `config_vip.json` | `"vip"` | route ber-`source: "vip"` |

### RDP Windows

1. Copy `config.example.json` → `config_vip.json`. Isi kredensial MT5 akun B + **`"source": "vip"`**.
2. Jalankan: `python signal_detector.py --config config_vip.json` (atau double-click `scripts/run_vip.bat`).
3. Tiap instance punya file sendiri, namanya ikut **nama file config** (`config` → default, `config_vip` → suffix `_config_vip`):
   | Instance | State | Log | Health | Checksum |
   |---|---|---|---|---|
   | `config.json` | `detector_state.json` | `detector.log` | `health.json` | `config_checksums.json` |
   | `config_vip.json` | `detector_state_config_vip.json` | `detector_config_vip.log` | `health_config_vip.json` | `config_checksumsconfig_vip.json` |
   Jadi jangan bingung kalau log-nya bernama `detector_config_vip.log` — itu memang pasangan `config_vip.json`.
4. Remote config juga terpisah: instance VIP poll `?source=vip` → file `detector_config_vip.json` di VPS (edit via API yang sama dengan `?source=vip`). Kalau file itu belum ada di VPS, pull-nya no-op (config VIP murni lokal di RDP).


### Receiver (otomatis)

- Sinyal bawa `source` → route dengan `source` yang sama di `telegram_config.json` (route tanpa field `source` = publik).
- **Lock per source**: posisi XAUUSD di akun publik gak nge-suppress XAUUSD di akun VIP (dan sebaliknya).
- **Anti-bocor**: sinyal `source: "vip"` tanpa route vip → **dibuang** dengan log jelas, BUKAN diterusin ke channel publik.
- Flag `test: true` tetap override ke channel TEST apapun source-nya.
- Route baru buat VIP (contoh):
  ```json
  {"name": "vip", "chat_id": -100XXXXXXXXXX, "source": "vip", "enabled": true}
  ```
  Set via API `POST /api/config/telegram` (selfbot hot-reload ≤5s).

---

**GitHub Repo:** https://github.com/Nabenns/mt5-signal  
**Receiver/VPS:** hirmes.bensserver.cloud
