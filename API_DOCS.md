# Signal Relay API - Dokumentasi Lengkap

## Overview
RESTful API untuk manajemen sinyal trading MT5 ke Telegram. Endpoint utama untuk dashboard/web frontend.

**Base URL:** `http://localhost:8080` (atau IP server Anda)  
**Port default:** 8080

---

## Endpoints

### 1. Health Check

```http
GET /api/health
```

**Response:**
```json
{
  "status": "ok",
  "timestamp": "2026-08-16T20:35:39.123456+00:00",
  "port": 8080,
  "stats": {
    "active_positions": 2,
    "pending_orders": 0,
    "locked_symbol_count": 2
  }
}
```

**Kegunaan:** Monitor kesehatan sistem & jumlah posisi aktif.

---

### 2. List Active Positions

```http
GET /api/positions
```

**Response:**
```json
{
  "count": 2,
  "data": [
    {
      "symbol": "BTCUSD",
      "position_id": 920001,
      "price": 63070.0,
      "opened_at": 1723842339.123,
      "status": "active"
    },
    {
      "symbol": "XAUUSD",
      "position_id": 920002,
      "price": 4000.0,
      "opened_at": 1723842340.456,
      "status": "active"
    }
  ]
}
```

**Kegunaan:** Ambil daftar posisi yang sedang active.

---

### 3. Recent Logs

```http
GET /api/logs?limit=50
```

**Response:**
```json
{
  "count": 10,
  "data": [
    "[2026-08-16T20:30:28] SENT COMPLETE: SELL BTCUSD SL=63110 TP=62910",
    "[2026-08-16T20:30:28] ENQUEUE ENTRY: SELL BTCUSD @ 63010.148",
    "[2026-08-16T20:30:29] ENQUEUE SLTP: BTCUSD SL=63110.3 TP=62910.0 (+1s)"
  ]
}
```

**Kegunaan:** Debugging & monitoring log sistem.

---

### 4. Raw State (Gunakan dengan hati-hati!)

```http
GET /api/state
```

**Response:**
```json
{
  "active": {
    "BTCUSD": {
      "position": 920001,
      "ts": 1723842339.123,
      "price": 63070.0
    }
  },
  "pending": {}
}
```

**Kegunaan:** Akses langsung ke state internal system.

---

### 5. Reset System (Requires Auth)

```http
POST /api/reset
Authorization: Bearer <your-secret>
```

**Response:**
```json
{
  "status": "reset complete"
}
```

**Kegunaan:** Clear semua lock, pending, dan logs. Gunakan saat ada masalah atau bug.

---

### 6. Webhook dari MT5 EA (Primary)

```http
POST /api/signal
Content-Type: application/json
Authorization: Bearer <your-secret>
```

**Request Body (Action: OPEN):**
```json
{
  "action": "OPEN",
  "symbol": "#BTCUSD",
  "type": "BUY",
  "lot": 0.1,
  "price": 63070.35,
  "sl": 62870.0,
  "tp": 63270.0,
  "deal": 920001,
  "position": 920001,
  "digits": 2
}
```

**Response:**
```json
{
  "status": "sent",
  "merged": true
}
```

**Request Body (Action: SLTP):**
```json
{
  "action": "SLTP",
  "symbol": "BTCUSD",
  "position": 920001,
  "sl": 62870.0,
  "tp": 63270.0,
  "digits": 2
}
```

**Request Body (Action: CLOSE):**
```json
{
  "action": "CLOSE",
  "position": 920001
}
```

**Status Codes:**
- `200 OK` → Success
- `200 {"status": "holding"}` → Entry tanpa SL/TP (nunggu update)
- `200 {"status": "suppressed", "reason": "position_active"}` → Symbol sudah punya posisi aktif
- `200 {"status": "ignored", "reason": "no_pending_entry"}` → SLTP bukan untuk pending entry

---

## Authentication

Semua endpoint POST (`/api/reset`, `/api/signal`) memerlukan authorization header atau query parameter:

```
Authorization: Bearer YOUR_SECRET_TOKEN
```

Atau via query string:
```
https://localhost:8080/api/signal?secret=YOUR_SECRET_TOKEN
```

**Secret token tersedia di file:** `.env` → `RECEIVER_SECRET`

---

## Instalasi & Running

### 1. Install dependencies (kalau belum ada)
```bash
pip3 install requests python-dateutil
```

### 2. Start API Server
```bash
cd /root/mt5-signal
python3 api_server.py
```

Server akan running di `http://localhost:8080`.

### 3. Test dengan cURL

#### Health check
```bash
curl http://localhost:8080/api/health
```

#### Buka posisi baru
```bash
curl -X POST http://localhost:8080/api/signal \
  -H "Content-Type: application/json" \
  -d '{"action":"OPEN","symbol":"BTCUSD","type":"BUY","lot":0.1,"price":63070.35,"sl":62870.0,"tp":63270.0,"deal":920001,"position":920001,"digits":2}'
```

#### Update SL/TP
```bash
curl -X POST http://localhost:8080/api/signal \
  -H "Content-Type: application/json" \
  -d '{"action":"SLTP","symbol":"BTCUSD","position":920001,"sl":62870.0,"tp":63270.0,"digits":2}'
```

#### Close position
```bash
curl -X POST http://localhost:8080/api/signal \
  -H "Content-Type: application/json" \
  -d '{"action":"CLOSE","position":920001}'
```

#### Reset system
```bash
curl -X POST http://localhost:8080/api/reset \
  -H "Authorization: Bearer YOUR_SECRET_TOKEN"
```

---

## Integrasi dengan Dashboard Web

### Contoh menggunakan Fetch API (JavaScript)

```javascript
const API_BASE = 'http://localhost:8080';
const SECRET = 'your_secret_token';

async function getHealth() {
  const resp = await fetch(`${API_BASE}/api/health`);
  return resp.json();
}

async function getPositions() {
  const resp = await fetch(`${API_BASE}/api/positions`);
  return resp.json();
}

async function openPosition(data) {
  const resp = await fetch(`${API_BASE}/api/signal?secret=${SECRET}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'OPEN', ...data })
  });
  return resp.json();
}

async function closePosition(positionId) {
  const resp = await fetch(`${API_BASE}/api/signal?secret=${SECRET}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'CLOSE', position: positionId })
  });
  return resp.json();
}

// Usage
getHealth().then(console.log);
getPositions().then(pos => console.log('Active:', pos.data));
```

---

## Contoh Frontend Simple (HTML/JS)

Simpan sebagai `dashboard.html`:

```html
<!DOCTYPE html>
<html lang="id">
<head>
  <meta charset="UTF-8">
  <title>Signal Relay Dashboard</title>
  <style>
    body { font-family: sans-serif; background: #1a1a1a; color: #fff; padding: 20px; }
    .card { background: #2a2a2a; border-radius: 8px; padding: 15px; margin-bottom: 10px; }
    h1 { color: #6b9c3e; }
    button { background: #6b9c3e; color: white; border: none; padding: 8px 16px; cursor: pointer; border-radius: 4px; }
    button:hover { opacity: 0.8; }
  </style>
</head>
<body>
  <h1>🚀 Signal Relay Dashboard</h1>
  
  <div class="card">
    <h2>📊 Health Status</h2>
    <pre id="health"></pre>
  </div>
  
  <div class="card">
    <h2>📈 Active Positions</h2>
    <ul id="positions"></ul>
  </div>
  
  <div class="card">
    <h2>⏱️ Log Terakhir</h2>
    <pre id="logs"></pre>
  </div>

  <script>
    const API_BASE = 'http://localhost:8080';
    const SECRET = 'your_secret_token_here';
    
    async function loadAll() {
      try {
        const health = await fetch(`${API_BASE}/api/health`).then(r => r.json());
        document.getElementById('health').textContent = JSON.stringify(health, null, 2);
        
        const positions = await fetch(`${API_BASE}/api/positions`).then(r => r.json());
        const ul = document.getElementById('positions');
        ul.innerHTML = '';
        positions.data.forEach(p => {
          const li = document.createElement('li');
          li.textContent = `${p.symbol} ID:${p.position_id} @ ${p.price}`;
          ul.appendChild(li);
        });
        
        const logs = await fetch(`${API_BASE}/api/logs?limit=20`).then(r => r.json());
        document.getElementById('logs').textContent = logs.data.join('\n') || 'No logs';
      } catch (e) {
        console.error('Error loading data:', e);
      }
    }
    
    // Auto-refresh every 5 seconds
    setInterval(loadAll, 5000);
    loadAll();
  </script>
</body>
</html>
```

Buka di browser: `file:///path/to/dashboard.html` atau serve dengan HTTP server lokal.

---

## Troubleshooting

### Q: API tidak merespon
A: Cek apakah server masih jalan:
```bash
ps aux | grep api_server
```
Jika mati, restart:
```bash
cd /root/mt5-signal
python3 api_server.py
```

### Q: Posisi tidak terkirim
A: Cek log:
```bash
curl http://localhost:8080/api/logs?limit=20
```

### Q: Position locked forever
A: Reset state:
```bash
curl -X POST http://localhost:8080/api/reset \
  -H "Authorization: Bearer YOUR_SECRET"
```

---

## Catatan Penting

1. **Lock per symbol**: Mencegah multiple entries di simbol yang sama sekaligus. Close semua posisi lama sebelum tes new.
2. **Grace period 120 detik**: Kalau SL/TP tidak lengkap dalam 2 menit, entry tetap dikirim tanpa SL/TP.
3. **Auto-unlock**: CLOSE event akan melepas lock otomatis.
4. **State persistence**: Semua data tersimpan di `state.json`, aman restart server.

---

## Security Notes

- Jangan expose port 8080 ke internet tanpa firewall/proxy
- Ganti `RECEIVER_SECRET` di file `.env` dengan value unik
- Gunakan HTTPS proxy (nginx/caddy) untuk production
- Batasi akses via IP whitelist jika memungkinkan

---

**Version:** 2.0  
**Author:** Signal Relay Team  
**License:** MIT
