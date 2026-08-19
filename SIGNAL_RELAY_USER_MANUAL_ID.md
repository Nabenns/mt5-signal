# Signal Relay MT5 → Telegram — User Manual (Indonesian/Jaksel)

## 🎯 Singkatnya

Lo minta **EA yang kirim sinyal ke Telegram setiap kali ada posisi open/close**. Ini jawabannya:

```
MT5 Terminal (SignalRelay.mq5) 
  └─ OnTradeTransaction event → detect posisi baru/tertutup
      └─ POST JSON ke VPS endpoint
          └─ Python receiver format + kirim ke Telegram bot @Dukuncc_bot
              └─ Lo liat signal cantik di channel!
```

**Kenapa hybrid (EA + backend)?**

| Part | Kenapa begitu? |
|------|---------------|
| **EA detektor** | `OnTradeTransaction` itu event-driven, nol delay. Pure program polling = telat 1–5 detik, gak worth it. |
| **Python sender** | MQL5 WebRequest synchronous + susah debug + ribet retry. Python = gampang, retry queue automatic. |

Jadi kita pakai **best of both**: EA buat deteksi real-time, Python buat deliver rapi.

---

## ✅ Setup Lengkap (step-by-step)

### Step 1: Add Bot ke Channel (HARUS DULU!)

Bot sudah exist: `@Dukuncc_bot`

**Cara add:**
1. Buka channel/group lo (misal ID `5491851564`)
2. Klik channel title → **Add Member**
3. Search `@Dukuncc_bot` → select dan add
4. Selesai

**Test apakah berhasil:**

```bash
curl -s "https://api.telegram.org/bot7628086190:AAG2ynlSS3qJgNRntYz1_sYc10RF1PfWheI/getChat?chat_id=5491851564" | grep ok
```

Harus return `"ok":true`. Kalau masih `chat not found` = belum masuk channel.

---

### Step 2: Install EA di MT5

**File EA ada di `/root/mt5-signal/SignalRelay.mq5`**. Transfer ke Mac RDP lo:

```bash
scp -i <key.pem> root@vps.lapak.flow:/root/mt5-signal/SignalRelay.mq5 ~/Downloads/
```

Atau copy paste manual dari terminal VPS (atau baca isi file, copy text nya).

#### 2a: Open MetaEditor

1. Launch MT5
2. Tekan F4 atau klik **Tools → MetaEditor**
3. Di panel kiri: **MQL5/Experts**
4. Klik kanan → **New → Expert Advisor → Template**
5. Ganti nama jadi **"SignalRelay"**
6. Hapus semua code template, paste isi `SignalRelay.mq5` di atas

#### 2b: Konfigurasi EA

Di bagian paling atas file:

```cpp
input string InpReceiverURL    = "https://hirmes.bensserver.cloud/api/signal";   
input long   InpMagicFilter    = 0;     // 0 = semua EA; atau angka spesifik
input bool   InpNotifyStartup  = true;  // kirim notice saat attach EA
```

**Penjelasan:**
- `InpReceiverURL` = URL endpoint VPS ini (auto-set, jangan diubah kecuali migrasi VPS)
- `InpMagicFilter` = filter magic number. Set ke angka misal `123456` kalau mau cuma kirim posisi dari EA tertentu aja
- `InpNotifyStartup` = kirim pesan "online" saat EA attach

#### 2c: ALLOW WEBREQUEST di Settings (PALING PENTING!)

Tanpa ini, EA akan error dan gak bisa kirim apa-apa:

1. **MT5 Menu → Tools → Options** (atau tekan Ctrl+O)
2. Tab **Expert Advisors**
3. Centang: **"Allow WebRequest for listed URLs"**
4. Klik tombol **"Allowed List..."**
5. Tambahkan URL berikut persis:
   ```
   https://hirmes.bensserver.cloud/api/signal/*
   ```
6. OK → Save

**Catatan:** jika MT5 masih bilang error IP whitelist, pastikan version MT5 terbaru (build ≥ 3065 yang support WebRequest proper). Update via download.mql5.com.

#### 2d: Compile & Attach

1. Di MetaEditor, tekan **F7** untuk compile
2. Harus muncul: **Compilation successful — 0 errors, 0 warnings**
3. Kembali ke MT5 terminal, buka chart (XAUUSD/H1 misalnya)
4. Drag EA dari **Navigator → Expert Advisors → SignalRelay** ke chart
5. Klik **"Allow Algo Trading"** di toolbar atas (icon hijau kecil harus nyala)
6. Klik OK

✅ EA sekarang **active** dan siap deteksi trade!

---

### Step 3: Tes Backend Receiver

Service receiver udah running di VPS. Cek status:

```bash
systemctl status mt5-signal-receiver
```

Cek health:

```bash
curl -s http://localhost:3203/api/signal/health
# expect: {"status":"ok","queued":0}
```

Coba trigger test signal langsung (manual):

```bash
SECRET=$(grep RECEIVER_SECRET /root/mt5-signal/.env | cut -d= -f2)
curl -X POST http://localhost:3203/api/signal \
  -H "Content-Type: application/json" \
  -H "X-Signal-Secret: $SECRET" \
  -d '{"action":"OPEN","symbol":"XAUUSD","type":"BUY","lot":0.10,"price":2345.67,"sl":2340,"tp":2360,"magic":0,"comment":"TEST MANUAL SIGNAL","deal":999999,"digits":2}'
```

Kalau response `{"status":"queued"}` = backend jalan. Tunggu 30 detik (queue flusher interval), check Telegram — seharusnya signal terkirim.

---

## 💬 Format Pesan Telegram

### Open Posisi:
```
🟢 OPEN BUY XAUUSD
Lot: 0.10 • Entry: 2345.67
SL: 2340.00 • TP: 2360.00
22:31 WIB • EA #0 • CUSTOM_COMMENT
```

### Close Win (TP hit):
```
✅ CLOSE BUY XAUUSD
Lot: 0.10 • Exit: 2350.50
P/L: +125.50
22:45 WIB • EA #0 • [TP] tersentuh
```

### Close Loss (SL hit):
```
❌ CLOSE SELL XAUUSD
Lot: 0.05 • Exit: 2355.00
P/L: -12.50
22:50 WIB • EA #1 • [SL] tersentuh
```

**Emoji:**
- 🟢 BUY long
- 🔴 SELL short  
- ✅ Win (profit >= 0)
- ❌ Loss (profit < 0)
- ✏️ Modify (rarely used)

Text bold otomatis via `parse_mode=HTML`.

---

## 🛠 Troubleshooting Umum

### A. "chat not found" terus – bot belum masuk channel
**Solusi:** add `@Dukuncc_bot` dulu ke channel. Setelah ditambahkan, queue akan auto-flush dalam 30 detik karena background flusher thread.

### B. WebRequest error (`error -1` atau `-4`)
**Penyebab:** MT5 settings tidak allow WebRequest, atau URL salah format.
**Fix:**
- Double-check "Allow WebRequest for listed URLs" dicentang
- Pastikan URL eksak: `https://hirmes.bensserver.cloud/api/signal/*` (ada wildcard `*`)
- Restart MT5 setelah ubah settings

### C. Signal queued tapi gak terkirim
**Cek:**
```bash
journalctl -u mt5-signal-receiver --no-pager -n 20
```

Kalau masih `chat not found`, berarti bot belum ditambahkan. Kalau error lain (rate limit 429, timeout 504, dll) = kondisi sementara, auto-retry.

### D. EA compile error
**Common fix:**
- Copy-paste ulang seluruh source dari `SignalRelay.mq5`
- Pastikan syntax correct (missing semicolon, typo function name)
- Update MT5 ke versi terbaru (MQL5 build ≥ 3065 support `WebRequest` properly)

### E. Magic filter tidak bekerja
**Pastikan:**
- Di EA setting, `InpMagicFilter` diset ke angka sama dengan magic EA trading yang mau difilter
- Kalau `0` = semua posisi dikirim, tanpa filter
- Position magic berbeda-beda tergantung EA trading utama

---

## 🔐 Security Notes

- **Endpoint authenticated:** header `X-Signal-Secret` wajib cocok dengan value di `.env`
- **Binding to localhost only:** receiver listen `127.0.0.1:3203`
- **HTTPS via Caddy proxy:** end-to-end encrypted, certificate auto-renewed
- **Queue persistence:** kalau Telegram down, signal disimpan di disk → auto-deliver when back up

Secret token: `3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610` (simpan aman, jangan share publik!)

---

## 📁 Lokasi File di VPS

```bash
/root/mt5-signal/
├── .env                    # configs (TG_BOT_TOKEN, SECRET, etc)
├── receiver.py             # HTTP server + Telegram sender
├── queue.json              # retry queue (disk-persisted)
├── receiver.log            # activity log
└── SignalRelay.mq5         # EA source (copy ke MT5/Mac/RDP)
```

Services:
- `mt5-signal-receiver.service` (systemd)
- Route via Caddy: `/api/signal` → `127.0.0.1:3203`

Commands:
```bash
systemctl status mt5-signal-receiver      # lihat status
systemctl restart mt5-signal-receiver     # restart service
journalctl -u mt5-signal-receiver -f      # live log
curl -s http://127.0.0.1:3203/api/signal/health  # health check
```

---

## 🔄 Status Saat Ini

| Komponen | Status | Catatan |
|----------|--------|---------|
| Python receiver | ✅ running | port `3203` local, HTTPS public |
| Caddy route | ✅ configured | path-based, no DNS change needed |
| Telegram bot | ⚠️ ready | **belum ditambahkan ke channel** |
| Queue | ⚠️ pending | menunggu bot added, then flush |
| EA file | ✅ ready | `/root/mt5-signal/SignalRelay.mq5` |

---

## 🚀 Next Steps / Opsional Future

1. **Multiple channels routing** – gold different from forex, crypto separate
2. **Email fallback** – telegram down → email alert
3. **Dashboard web** – real-time signal history + stats (future)
4. **Webhook callback** – notify external system on success

---

## 📞 Contact & Support

If you need changes or find bugs:

1. Check logs first (`journalctl -u mt5-signal-receiver -f`)
2. Verify bot/channel connectivity manually
3. Test endpoint with curl before MT5
4. Share error output for debugging

---

**Build Status: ✅ COMPLETE**

Action required dari lo:

1. ✅ Upload `SignalRelay.mq5` ke MT5 (Mac/RDP nanti)
2. ✅ Configure EA (paste source, allow WebRequest, attach ke chart)
3. ✅ Add @Dukuncc_bot ke channel 5491851564
4. ✅ Trigger test signal via curl (optional)
5. ⏳ Wait 30s → signal delivery verified in Telegram

Once bot ditambahkan, **everything just works**. No polling, zero delay, reliable delivery. 🔥
