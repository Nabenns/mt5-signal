"""
MT5 Signal Receiver v10 — Wait-for-complete mode.

Rules (final, per user):
1. Entry masuk tanpa SL/TP lengkap -> HOLD. Jangan kirim dulu.
2. Begitu SL & TP DUA-DUANYA > 0 -> KIRIM LANGSUNG (minim delay):
   - Message 1: ENTRY  ("BUY NOW XAUUSD 4820")
   - Message 2: SL/TP  ("SL 4815 | TP 4835") — terpisah, jeda 1 detik
3. Kalau cuma salah satu (SL doang / TP doang) -> tetap hold, nunggu yang satu lagi.
4. Safety: kalau gak lengkap dalam GRACE detik -> kirim entry doang (tanpa SL/TP).
5. Adjust SL/TP SETELAH terkirim -> DIABAIKAN (no update).
6. Lock per symbol: posisi A aktif -> entry B di symbol sama di-suppress.
7. CLOSE -> lock lepas + buang pending.

Actions dari EA: OPEN, SLTP, CLOSE, NOTICE.
Output: sb_queue.json (dikonsumsi selfbot.py).
"""

import json
import os
import threading
import time
import hashlib
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE = os.path.dirname(os.path.abspath(__file__))

# ---- config ----
ENV = {}
with open(os.path.join(BASE, ".env")) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            ENV[k.strip()] = v.strip()

SECRET = ENV["RECEIVER_SECRET"]
PORT = int(ENV.get("PORT", "3203"))
SLTP_GAP_SECONDS = 1         # jeda antara msg ENTRY dan msg SL/TP (biar urut & natural)
GRACE_SECONDS = 15           # kalau SL/TP gak lengkap dalam 15s, kirim entry doang
STALE_LOCK_SECONDS = 86400   # lock auto-lepas setelah 24 jam (safety)
WIB = timezone(timedelta(hours=7))

SB_QUEUE_FILE = os.path.join(BASE, "sb_queue.json")
STATE_FILE = os.path.join(BASE, "state.json")
LOG_FILE = os.path.join(BASE, "receiver.log")
DETECTOR_CONFIG_FILE = os.path.join(BASE, "detector_config.json")

_lock = threading.Lock()
_seen_events = {}


# ---- detector config (remote-managed, source of truth di VPS) ----
DEFAULT_DETECTOR_CONFIG = {
    "mt5": {
        "login": 0,
        "password": "***",
        "server": "",
        "terminal_path": "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
    },
    "settings": {
        "poll_interval": 1.0,
        "health_interval": 60,
        "startup_seed_minutes": 5,
        "notify_restart": True,
        "config_poll_interval": 30,
    },
    "meta": {"version": 0, "updated_at": 0},
}


def load_detector_config():
    try:
        with open(DETECTOR_CONFIG_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_DETECTOR_CONFIG))


def save_detector_config(cfg):
    cfg["meta"]["version"] = int(cfg.get("meta", {}).get("version", 0)) + 1
    cfg["meta"]["updated_at"] = time.time()
    # checksum dari isi (tanpa meta) biar detector bisa detect perubahan
    payload = json.dumps({"mt5": cfg["mt5"], "settings": cfg["settings"]}, sort_keys=True)
    cfg["meta"]["checksum"] = hashlib.sha256(payload.encode()).hexdigest()[:16]
    tmp = DETECTOR_CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, DETECTOR_CONFIG_FILE)
    return cfg


def deep_merge(base, new):
    """Merge dict new ke base (nested), return base."""
    for k, v in new.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def log(msg):
    line = f"[{datetime.now(WIB).strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---- persistence ----
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"active": {}, "pending": {}}


def save_state(st):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, STATE_FILE)


def load_sb_queue():
    try:
        with open(SB_QUEUE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_sb_queue(q):
    tmp = SB_QUEUE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(q, f)
    os.replace(tmp, SB_QUEUE_FILE)


# ---- queue builders ----
def enqueue_entry(sig):
    q = load_sb_queue()
    q.append({
        "type": "ENTRY",
        "symbol": sig.get("symbol"),
        "type_": sig.get("type"),
        "price": sig.get("price"),
        "sl": 0,
        "tp": 0,
        "digits": int(sig.get("digits", 2)),
        "position": sig.get("position"),
        "deal": sig.get("deal"),
        "ts": time.time(),
    })
    save_sb_queue(q)
    log(f"📤 ENQUEUE ENTRY: {sig.get('type')} {sig.get('symbol')} @ {sig.get('price')}")


def enqueue_notice(text):
    """Send system notice to Telegram (non-trade alert)."""
    q = load_sb_queue()
    q.append({
        "type": "NOTICE",
        "text": text,
        "ts": time.time(),
    })
    save_sb_queue(q)
    log(f"📤 NOTIFICATION: {text[:50]}")


def enqueue_sltp(sig, delay):
    q = load_sb_queue()
    q.append({
        "type": "SLTP",
        "symbol": sig.get("symbol"),
        "sl": sig.get("sl"),
        "tp": sig.get("tp"),
        "deal": sig.get("deal"),
        "position": sig.get("position"),
        "ts": time.time(),
        "send_after": time.time() + delay,
    })
    save_sb_queue(q)
    log(f"📤 ENQUEUE SLTP: {sig.get('symbol')} SL={sig.get('sl')} TP={sig.get('tp')} (+{delay}s)")


def send_complete(st, sig):
    """Kirim entry + SL/TP (terpisah kalau ada), set lock active."""
    enqueue_entry(sig)
    if float(sig.get("sl") or 0) > 0 or float(sig.get("tp") or 0) > 0:
        enqueue_sltp(sig, SLTP_GAP_SECONDS)
    st["active"][sig["symbol"]] = {
        "position": sig.get("position"),
        "ts": time.time(),
        "price": sig.get("price"),
    }
    log(f"✅ SENT COMPLETE: {sig.get('type')} {sig.get('symbol')} SL={sig.get('sl')} TP={sig.get('tp')}")


def send_entry_only(st, sig):
    """Kirim entry doang (fallback saat grace habis tanpa SL/TP lengkap)."""
    enqueue_entry(sig)
    st["active"][sig["symbol"]] = {
        "position": sig.get("position"),
        "ts": time.time(),
        "price": sig.get("price"),
    }
    log(f"⌛ SENT ENTRY-ONLY (grace expired): {sig.get('type')} {sig.get('symbol')}")


# ---- handlers (dipanggil sambil pegang _lock) ----
def on_open(st, d):
    symbol = d.get("symbol")
    position = d.get("position") or 0
    deal = d.get("deal") or 0
    now = time.time()

    # Lock check: masih ada posisi aktif di symbol ini?
    act = st["active"].get(symbol)
    if act and (now - act.get("ts", 0)) < STALE_LOCK_SECONDS:
        log(f"🚫 SUPPRESS {symbol}: posisi {act.get('position')} masih aktif")
        return {"status": "suppressed", "reason": "position_active"}

    sl = float(d.get("sl") or 0)
    tp = float(d.get("tp") or 0)

    # Entry udah bawa SL/TP (EA udah nunggu lengkap/grace) -> kirim sekarang juga
    if sl > 0 or tp > 0:
        send_complete(st, d)
        return {"status": "sent"}

    # Belum lengkap -> HOLD, tunggu event SLTP
    key = f"{symbol}:{deal or position}"
    st["pending"][key] = {
        "symbol": symbol,
        "type": d.get("type"),
        "price": d.get("price"),
        "sl": sl,
        "tp": tp,
        "digits": d.get("digits", 2),
        "position": position,
        "deal": deal,
        "deadline": now + GRACE_SECONDS,
    }
    log(f"⏳ HOLD {symbol} deal {deal} — nunggu SL & TP lengkap")
    return {"status": "holding"}


def on_sltp(st, d):
    symbol = d.get("symbol")
    position = d.get("position") or 0
    deal = d.get("deal") or 0
    sl = float(d.get("sl") or 0)
    tp = float(d.get("tp") or 0)

    # Cari pending entry yang cocok
    matched_key = None
    for key, pend in st["pending"].items():
        if pend["symbol"] != symbol:
            continue
        if (deal > 0 and pend.get("deal") == deal) or \
           (position > 0 and pend.get("position") == position):
            matched_key = key
            break

    if not matched_key:
        # Sudah terkirim / gak dikenal -> adjust DIABAIKAN
        log(f"🚫 SLTP adjust {symbol} pos {position} diabaikan (entry udah terkirim / bukan pending)")
        return {"status": "ignored", "reason": "no_pending_entry"}

    pend = st["pending"][matched_key]
    # Merge cuma nilai yang > 0 (drag SL dulu, TP nyusul — atau sebaliknya)
    if sl > 0:
        pend["sl"] = sl
    if tp > 0:
        pend["tp"] = tp

    # Belum lengkap -> tetap hold
    if not (pend["sl"] > 0 and pend["tp"] > 0):
        log(f"⏳ SLTP partial {symbol} (SL={pend['sl']}, TP={pend['tp']}) — masih nunggu")
        return {"status": "holding_partial"}

    # Lengkap -> cek lock DOOR HANYA jikab position aktif SAMA PERIS dengan pending entry
    now = time.time()
    act = st["active"].get(symbol)
    
    # JANGAN suppress! Kita mau kirim entry + SLTP barengan (ini kasus normal)
    # Suppression hanya untuk MULTI-ENTRY attack prevention
    if act and act.get("position") == position:
        # Position ACTIVE DAN SAMA DENGAN PENDING -> berarti ini entry baru yang valid
        # Kirim aja! Jangan suppress
        pass
    elif act and act.get("position") != position:
        # Position aktif LAIN (attack attempt?) -> suppress
        del st["pending"][matched_key]
        log(f"🚫 SUPPRESS {symbol}: posisi {act.get('position')} berbeda dengan pending {position}")
        return {"status": "suppressed", "reason": "different_position_active"}

    del st["pending"][matched_key]
    send_complete(st, pend)
    
    return {"status": "sent", "merged": True}


def on_close(st, d):
    symbol = d.get("symbol")
    position = d.get("position") or 0

    act = st["active"].get(symbol)
    if act and act.get("position") == position:
        del st["active"][symbol]
        log(f"🔓 CLOSE {symbol} pos {position} — lock dilepas")
    elif act:
        log(f"ℹ️ CLOSE {symbol} pos {position} (lock aktif posisi {act.get('position')})")

    # Buang pending untuk posisi ini (close sebelum SL/TP lengkap)
    for key in list(st["pending"].keys()):
        pend = st["pending"][key]
        if pend["symbol"] == symbol and pend.get("position") == position:
            del st["pending"][key]
            log(f"🗑️ Pending {symbol} pos {position} dibuang (closed)")

    return {"status": "closed"}


def flush_expired(st):
    """Grace habis tanpa SL/TP lengkap -> kirim entry doang."""
    now = time.time()
    n = 0
    for key in list(st["pending"].keys()):
        pend = st["pending"][key]
        if pend["deadline"] <= now:
            del st["pending"][key]
            send_entry_only(st, pend)
            n += 1
    return n


def pending_flusher():
    while True:
        time.sleep(2)
        with _lock:
            st = load_state()
            n = flush_expired(st)
            if n:
                save_state(st)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj, cors=False):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        # ---- CORS support buat frontend lo ----
        def cors_headers():
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Signal-Secret, Authorization")

        if path == "/api/health" or path in ("/health", "/signal/health", "/api/signal/health"):
            with _lock:
                st = load_state()
                sb = load_sb_queue()
            self._json(200, {
                "status": "ok",
                "timestamp": datetime.now(WIB).isoformat(),
                "stats": {
                    "queued_selfbot": len(sb),
                    "pending_orders": len(st.get("pending", {})),
                    "active_locks": len(st.get("active", {})),
                },
                "active_locks": st.get("active", {}),
            }, cors=True)
        elif path == "/api/positions":
            # List active positions (buat dashboard)
            with _lock:
                st = load_state()
            positions = []
            for symbol, info in st.get("active", {}).items():
                positions.append({
                    "symbol": symbol,
                    "position_id": info.get("position"),
                    "price": info.get("price"),
                    "opened_at": info.get("ts"),
                    "status": "active",
                })
            self._json(200, {"count": len(positions), "data": positions}, cors=True)
        elif path == "/api/logs":
            # Recent logs (buat dashboard debugging)
            try:
                with open(LOG_FILE) as f:
                    lines = f.readlines()[-100:]
            except OSError:
                lines = []
            self._json(200, {"count": len(lines), "data": [l.strip() for l in lines]}, cors=True)
        
        # ---- Detector config (read) ----
        elif path == "/api/config/detector":
            # Auth required — config mengandung password MT5
            secret = self.headers.get("X-Signal-Secret") or self.headers.get("Authorization", "").replace("Bearer ", "")
            if not secret:
                qs = parse_qs(parsed.query)
                secret = qs.get("secret", [None])[0]
            if secret != SECRET:
                return self._json(401, {"error": "unauthorized"}, cors=True)
            # ?mask=1 → password di-mask (buat display di FE)
            qs = parse_qs(parsed.query)
            cfg = load_detector_config()
            if qs.get("mask", ["0"])[0] == "1":
                cfg = json.loads(json.dumps(cfg))
                pw = cfg["mt5"].get("password", "")
                cfg["mt5"]["password"] = ("•" * 8 + pw[-2:]) if pw else ""
            self._json(200, cfg, cors=True)
        
        elif path == "/api/config/detector/checksum":
            # Lightweight endpoint buat detector poll perubahan (no auth body leak)
            cfg = load_detector_config()
            self._json(200, {
                "version": cfg.get("meta", {}).get("version", 0),
                "checksum": cfg.get("meta", {}).get("checksum", ""),
            }, cors=True)
        
        else:
            self._json(404, {"error": "not found"}, cors=True)

    def do_OPTIONS(self):
        """CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Signal-Secret, Authorization")
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip('/')

        # ---- API: Reset system (requires auth) ----
        if path == "/api/reset":
            secret = self.headers.get("X-Signal-Secret") or self.headers.get("Authorization", "").replace("Bearer ", "")
            if not secret:
                qs = parse_qs(parsed.query)
                secret = qs.get("secret", [None])[0]
            if secret != SECRET:
                return self._json(401, {"error": "unauthorized"}, cors=True)
            with _lock:
                save_state({"active": {}, "pending": {}})
                save_sb_queue([])
            log("🔄 SYSTEM RESET via API")
            return self._json(200, {"status": "reset complete"}, cors=True)
        
        # ---- LEGACY: Screenshot config endpoints (disabled - feature removed) ----
        if path in ("/api/config/tv-links", "/api/config/channels"):
            return self._json(410, {
                "error": "Feature disabled", 
                "message": "TradingView screenshot feature has been removed"
            }, cors=True)
        
        # ---- Detector config (write) ----
        elif path == "/api/config/detector":
            secret = self.headers.get("X-Signal-Secret") or self.headers.get("Authorization", "").replace("Bearer ", "")
            if not secret:
                qs = parse_qs(parsed.query)
                secret = qs.get("secret", [None])[0]
            if secret != SECRET:
                return self._json(401, {"error": "unauthorized"}, cors=True)
            
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode('utf-8')
            try:
                req = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return self._json(400, {"error": "Invalid JSON"}, cors=True)
            
            with _lock:
                cfg = load_detector_config()
                # Merge hanya mt5 dan settings
                if "mt5" in req:
                    cfg["mt5"] = deep_merge(cfg["mt5"], req["mt5"])
                if "settings" in req:
                    cfg["settings"] = deep_merge(cfg["settings"], req["settings"])
                # Validasi basic
                if not cfg["mt5"].get("login"):
                    return self._json(400, {"error": "missing mt5.login"}, cors=True)
                if not cfg["mt5"].get("password") or cfg["mt5"]["password"] == "***":
                    return self._json(400, {"error": "missing/invalid mt5.password"}, cors=True)
                
                cfg = save_detector_config(cfg)
            
            log(f"✅ DETECTOR CONFIG UPDATED (v{cfg['meta']['version']}) — from {self.client_address[0]}")
            return self._json(200, {
                "status": "updated",
                "version": cfg["meta"]["version"],
                "checksum": cfg["meta"]["checksum"]
            }, cors=True)
        
        if path not in ("/signal", "/api/signal"):
            return self._json(404, {"error": "not found"})

        secret = self.headers.get("X-Signal-Secret")
        if not secret:
            qs = parse_qs(parsed.query)
            secret = qs.get("secret", [None])[0]
        if secret != SECRET:
            log(f"REJECT: secret salah dari {self.client_address[0]}")
            return self._json(401, {"error": "unauthorized"})

        try:
            length = int(self.headers.get("Content-Length", 0))
            d = json.loads(self.rfile.read(length).decode('utf-8'))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return self._json(400, {"error": "bad json"})

        action = (d.get("action") or "").upper()

        # dedup per event
        if action == "OPEN":
            dedup_key = ("OPEN", d.get("deal"), d.get("position"))
        elif action == "SLTP":
            dedup_key = ("SLTP", d.get("symbol"), d.get("position"), d.get("sl"), d.get("tp"))
        elif action == "CLOSE":
            dedup_key = ("CLOSE", d.get("position") or d.get("deal"))
        else:
            dedup_key = None

        if dedup_key:
            with _lock:
                if len(_seen_events) > 5000:
                    _seen_events.clear()
                now = time.time()
                if dedup_key in _seen_events and now - _seen_events[dedup_key] < 120:
                    return self._json(200, {"status": "duplicate"})
                _seen_events[dedup_key] = now

        with _lock:
            st = load_state()
            if action == "OPEN":
                res = on_open(st, d)
            elif action == "SLTP":
                res = on_sltp(st, d)
            elif action == "CLOSE":
                res = on_close(st, d)
            elif action == "NOTICE":
                enqueue_notice(d.get("text", ""))
                res = {"status": "sent"}
            else:
                res = {"status": "skipped", "reason": f"action_{action}"}
            save_state(st)

        return self._json(200, res)


def main():
    threading.Thread(target=pending_flusher, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    log(f"Receiver v10 (wait-for-complete) start di 127.0.0.1:{PORT}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
