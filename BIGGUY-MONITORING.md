# Instruksi Monitoring MT5 Signal Relay (untuk AI Big Guy)

Kamu (AI pengelola Big Guy Management System) dapat tugas mantau sistem signal relay di VPS yang sama.
Ini panduan lengkapnya. JALANKAN sesuai isi dokumen ini, jangan mengarang endpoint.

## 1. Apa sistem ini

Pipeline sinyal trading: **MT5 (RDP) → detector → receiver (VPS) → selfbot → Telegram**.

- **Receiver** — HTTP server port `3203`, file: `/root/mt5-signal/receiver.py`, service: `mt5-signal-receiver`
- **Selfbot** — pengirim Telegram (Telethon), file: `/root/mt5-signal/selfbot.py`, service: `mt5-signal-selfbot`
- **Detector** — jalan di RDP Windows (`mt5` = 100.86.92.56), 2 instance: publik + vip, masing-masing dengan terminal MT5 sendiri
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
| `GET /api/positions` | tidak | Daftar posisi aktif (lock, ada field `source`) |
| `GET /api/logs` | tidak | 100 log terakhir (param `limit` DIABAIKAN — selalu 100) |
| `POST /api/signal` | ya | Terima sinyal dari detector (JANGAN dipanggil sembarangan — masuk channel Telegram beneran) |
| `GET /api/config/telegram` | ya | Config akun/route Telegram (`?mask=1` buat masking api_hash) |
| `GET /api/config/detector?source=public` | ya | Config detector per akun (`?source=vip` untuk instance VIP) |
| `POST /api/reset` | ya | Reset sistem (bahaya, lihat aturan; `?force=true` buat lewati safety lock) |

**PENTING — `/api/state` TIDAK ADA di receiver** (balas 404). Kalau UI butuh state lock,
pakai `/api/positions` + `/api/health` (`active_locks` ikut dikirim di health).
`GET /api/config/detector/checksum` dan `/api/config/telegram/checksum` tidak butuh auth.

**Auth:** header `X-Signal-Secret: <isi RECEIVER_SECRET>` — secret ada di `/root/mt5-signal/.env` (baca: `sudo grep RECEIVER_SECRET /root/mt5-signal/.env`). JANGAN pernah tampilkan secret lengkap ke user — mask seperti `••••1234`.

URL publik yang sama: `https://hirmes.bensserver.cloud/api/...` (dipakai detector di RDP).

## 4. Aturan keselamatan (WAJIB)

1. **JANGAN panggil `POST /api/reset`** kecuali user minta eksplisit. Itu menghapus lock posisi.
2. **JANGAN POST ke `/api/signal`** kecuali user minta tes. Sinyal `test: true` aman (masuk channel test), tanpa flag itu masuk channel produksi beneran.
3. **JANGAN ubah `/api/config/telegram` / `/api/config/detector`** tanpa konfirmasi user — salah isi route = sinyal nyasar ke channel publik.
4. Monitoring = READ ONLY secara default: `/api/health`, `/api/positions`, `/api/logs`, `systemctl is-active`, baca log.
5. Restart service diperbolehkan kalau down: `sudo systemctl restart mt5-signal-receiver mt5-signal-selfbot`.
6. JANGAN sentuh Caddy block `hirmes.bensserver.cloud` (root path 404 = normal, API-only).

## 5. Channel Telegram (untuk referensi laporan)

| Route | chat_id | source | Keterangan |
|---|---|---|---|
| prod | `-1001816822545` | public | For Brother \| Trade — t.me/forbrotherclub |
| vip | `-1003913040101` (topik 9) | vip | Channel VIP, format `vip` |
| crazypauls | `-1003763075126` | vip | Partner channel, format `run50` |
| indicatorisme | `-1001732290104` | vip | Partner channel, format `indi` |
| test-public | `-5582588069` | public | Channel tes publik (aman buat uji) |
| test-vip | `-5507212729` | vip | Channel tes VIP (aman buat uji) |

Catatan routing: 1 sinyal VIP → fanout ke vip + crazypauls + indicatorisme.
Sinyal `public` → prod. Sinyal `test:true` → HANYA channel test (apapun source-nya).
Source tanpa route enabled → sinyal DIBUANG oleh receiver (anti-bocor, ada log 🚫 DROP).

Tes aman kirim sinyal uji (masuk channel test, bukan produksi):

```bash
SECRET=$(sudo grep '^RECEIVER_SECRET=' /root/mt5-signal/.env | cut -d= -f2-)
curl -s -H "X-Signal-Secret: $SECRET" -H "Content-Type: application/json" \
  -d '{"action":"OPEN","symbol":"XAUUSD","type":"BUY","lot":0.1,"price":4820.0,"sl":4815.0,"tp":4835.0,"digits":2,"deal":999901,"position":888901,"test":true,"source":"public"}' \
  http://127.0.0.1:3203/api/signal
```

## 6. Template integrasi di web Big Guy

Dashboard `/signal-monitor/` bisa poll `GET /api/health` tiap 30-60 detik (tanpa auth). Yang layak ditampilkan: `status`, `stats.queued_selfbot`, jumlah `active_locks`, timestamp. Untuk aksi (reset/config) wajib lewat konfirmasi user + header auth.

Catatan implementasi saat ini (`app/api/signal-monitor/route.ts` + `.../events/route.ts`): keduanya
fetch `/api/state` (404 → `state` selalu null) dan `/api/logs?limit=60` (limit diabaikan).
Kalau panel state mau berisi, ambil dari `/api/positions` + `/api/health.active_locks`.
Koneksinya juga http ke `127.0.0.1:3203` — receiver-bound (aman, tidak lewat internet).
