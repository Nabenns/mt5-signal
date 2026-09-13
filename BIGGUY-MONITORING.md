# Instruksi Monitoring MT5 Signal Relay (untuk AI Big Guy)

Kamu (AI pengelola Big Guy Management System) dapat tugas mantau sistem signal relay di VPS yang sama.
Ini panduan lengkapnya. JALANKAN sesuai isi dokumen ini, jangan mengarang endpoint.

## 1. Apa sistem ini

Pipeline sinyal trading: **MT5 (RDP) → detector → receiver (VPS) → selfbot → Telegram**.

- **Receiver** — HTTP server port `3203`, file: `/root/mt5-signal/receiver.py`, service: `mt5-signal-receiver`
- **Selfbot** — pengirim Telegram (Telethon), file: `/root/mt5-signal/selfbot.py`, service: `mt5-signal-selfbot`
- Semua file produksi: `/root/mt5-signal/` (butuh sudo; user `orca` punya NOPASSWD: ALL)

## 2. Cara cek kesehatan (lakukan berurutan)

```bash
# 1) Service hidup?
systemctl is-active mt5-signal-receiver mt5-signal-selfbot

# 2) Receiver jawab? (TANPA auth, aman dipoll tiap 30-60s)
curl -s http://127.0.0.1:3203/api/health

# 3) Antrian selfbot kosong? (sinyal numpuk = selfbot bermasalah)
curl -s http://127.0.0.1:3203/api/health | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['stats'])"

# 4) Log terakhir (kalau ada kejanggalan)
sudo tail -30 /root/mt5-signal/receiver.log
sudo tail -30 /root/mt5-signal/selfbot.log
sudo cat /root/mt5-signal/selfbot_health.json
```

**Interpretasi `/api/health`:**
- `status: "ok"` + `queued_selfbot: 0` → sehat
- `queued_selfbot` terus > 0 → selfbot gagal kirim (cek FloodWait / koneksi di selfbot.log)
- `active_locks` banyak & `ts`-nya lama (> 86400s) → lock basi, aman diabaikan (auto-expire 24 jam)
- Endpoint mati (connection refused) → receiver down, cek `journalctl -u mt5-signal-receiver -n 50`

## 3. Endpoint API receiver (port 3203)

| Endpoint | Auth | Fungsi |
|---|---|---|
| `GET /api/health` | tidak | Status + statistik queue/lock |
| `GET /api/positions` | tidak | Daftar posisi aktif (lock) |
| `GET /api/logs` | tidak | 100 log terakhir |
| `GET /api/signal` (POST di `/api/signal`) | ya | Terima sinyal dari detector (JANGAN dipanggil sembarangan — masuk channel Telegram beneran) |
| `GET /api/config/telegram` | ya | Config akun/route Telegram |
| `GET /api/config/detector?source=public` | ya | Config detector per akun |
| `POST /api/reset` | ya | Reset sistem (bahaya, lihat aturan) |

**Auth:** header `X-Signal-Secret: <isi RECEIVER_SECRET>` — secret ada di `/root/mt5-signal/.env` (baca: `sudo grep RECEIVER_SECRET /root/mt5-signal/.env`). JANGAN pernah tampilkan secret lengkap ke user — mask seperti `••••1234`.

URL publik yang sama: `https://hirmes.bensserver.cloud/api/...` (dipakai detector di RDP).

## 4. Aturan keselamatan (WAJIB)

1. **JANGAN panggil `POST /api/reset`** kecuali user minta eksplisit. Itu menghapus lock posisi.
2. **JANGAN POST ke `/api/signal`** kecuali user minta tes. Sinyal `test: true` aman (masuk channel test), tanpa flag itu masuk channel produksi beneran.
3. **JANGAN ubah `/api/config/telegram` / `/api/config/detector`** tanpa konfirmasi user — salah isi route = sinyal nyasar ke channel publik.
4. Monitoring = READ ONLY secara default: `/api/health`, `/api/positions`, `/api/logs`, `systemctl is-active`, baca log.
5. Restart service diperbolehkan kalau down: `sudo systemctl restart mt5-signal-receiver mt5-signal-selfbot`.

## 5. Channel Telegram (untuk referensi laporan)

| Route | chat_id | Keterangan |
|---|---|---|
| prod (publik) | `-1001816822545` | For Brother \| Trade — t.me/forbrotherclub |
| vip | `-3913040101` | Channel VIP |
| test-public | `-5582588069` | Channel tes publik (aman buat uji) |
| test-vip | `-5507212729` | Channel tes VIP (aman buat uji) |

Tes aman kirim sinyal uji (masuk channel test, bukan produksi):

```bash
SECRET=$(sudo grep '^RECEIVER_SECRET=' /root/mt5-signal/.env | cut -d= -f2-)
curl -s -H "X-Signal-Secret: $SECRET" -H "Content-Type: application/json" \
  -d '{"action":"OPEN","symbol":"XAUUSD","type":"BUY","lot":0.1,"price":4820.0,"sl":4815.0,"tp":4835.0,"digits":2,"deal":999901,"position":888901,"test":true,"source":"public"}' \
  http://127.0.0.1:3203/api/signal
```

## 6. Template integrasi di web Big Guy

Dashboard `/signal-monitor/` bisa poll `GET /api/health` tiap 30-60 detik (tanpa auth). Yang layak ditampilkan: `status`, `stats.queued_selfbot`, jumlah `active_locks`, timestamp. Untuk aksi (reset/config) wajib lewat konfirmasi user + header auth.
