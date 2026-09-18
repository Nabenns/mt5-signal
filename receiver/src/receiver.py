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

Actions dari detector: OPEN, SLTP, CLOSE, NOTICE.
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

# BASE adaptif: support dua layout — repo (receiver/src/receiver.py → BASE=receiver/)
# dan prod flat (/root/mt5-signal/receiver.py → BASE=dir file).
_HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(_HERE) if os.path.basename(_HERE) == "src" else _HERE  # receiver/

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
GRACE_SECONDS = 1            # kalau SL/TP gak lengkap dalam 1s, kirim entry doang
STALE_LOCK_SECONDS = 86400   # lock auto-lepas setelah 24 jam (safety)
WIB = timezone(timedelta(hours=7))

SB_QUEUE_FILE = os.path.join(BASE, "sb_queue.json")
STATE_FILE = os.path.join(BASE, "state.json")
LOG_FILE = os.path.join(BASE, "receiver.log")
DETECTOR_CONFIG_FILE = os.path.join(BASE, "detector_config.json")

_lock = threading.Lock()
_seen_events = {}


# ---- detector config (remote-managed, source of truth di VPS) ----
# Multi akun MT5: tiap detektor punya config sendiri, dipilih via ?source=
# di API (detektor VIP poll ?source=vip → file detector_config_vip.json).
DEFAULT_DETECTOR_SOURCE = "public"


def _detector_cfg_file(source=None):
    s = str(source or "").strip().lower()
    if not s or s == DEFAULT_DETECTOR_SOURCE:
        return DETECTOR_CONFIG_FILE
    return os.path.join(BASE, f"detector_config_{s}.json")


def load_detector_config(source=None):
    try:
        with open(_detector_cfg_file(source)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_DETECTOR_CONFIG))


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
        "limit_area_range": 2,
        "limit_sl_distance": 5,
    },
    "meta": {"version": 0, "updated_at": 0},
}


def save_detector_config(cfg, source=None):
    cfg["meta"] = cfg.get("meta", {})
    cfg["meta"]["version"] = int(cfg["meta"].get("version", 0)) + 1
    cfg["meta"]["updated_at"] = time.time()
    # checksum dari isi (tanpa meta) biar detector bisa detect perubahan
    payload = json.dumps({"mt5": cfg["mt5"], "settings": cfg["settings"]}, sort_keys=True)
    cfg["meta"]["checksum"] = hashlib.sha256(payload.encode()).hexdigest()[:16]
    path = _detector_cfg_file(source)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)
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
            st = json.load(f)
    except (OSError, ValueError):
        return {"active": {}, "pending": {}}
    # Migrasi state lama (key "SYMBOL") → per-source ("source|SYMBOL").
    # Entry tanpa prefix = sinyal dari detektor default → 'public'.
    old = st.get("active", {})
    new = {}
    for k, v in old.items():
        if "|" in k:
            v.setdefault("source", k.split("|", 1)[0])
            new[k] = v
        else:
            v["source"] = "public"
            new[f"public|{k}"] = v
    st["active"] = new
    return st


def _active_key(sig):
    """Key lock per source: 'vip|XAUUSD'. Akun beda gak saling blokir."""
    return f"{_norm_source(sig)}|{sig.get('symbol')}"


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
# Channel tujuan sekarang data-driven dari telegram_config.json (multi akun + multi channel).
# Flag "test": true → WAJIB ke route test. Tanpa config → fallback PROD/TEST lama.
TEST_CHAT_ID = -1004479253024   # test channel (channel lama, fallback)
TELEGRAM_CONFIG_FILE = os.path.join(BASE, "telegram_config.json")

DEFAULT_TELEGRAM_CONFIG = {"accounts": [], "routes": []}


def load_telegram_config():
    try:
        with open(TELEGRAM_CONFIG_FILE) as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            return json.loads(json.dumps(DEFAULT_TELEGRAM_CONFIG))
        return cfg
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_TELEGRAM_CONFIG))


def save_telegram_config(cfg):
    cfg.setdefault("meta", {})
    cfg["meta"]["version"] = int(cfg["meta"].get("version", 0)) + 1
    cfg["meta"]["updated_at"] = time.time()
    payload = json.dumps({"accounts": cfg.get("accounts", []), "routes": cfg.get("routes", [])}, sort_keys=True)
    cfg["meta"]["checksum"] = hashlib.sha256(payload.encode()).hexdigest()[:16]
    tmp = TELEGRAM_CONFIG_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, TELEGRAM_CONFIG_FILE)
    return cfg


def _norm_source(sig):
    """Normalisasi source sinyal: '' / tanpa field → 'public'."""
    s = str((sig or {}).get("source") or "").strip().lower()
    return s or "public"


def route_targets(sig):
    """Pilih daftar route tujuan untuk satu sinyal (hasil: list dict route).

    Rules:
    1. sig.test == True → cuma route yang bertanda test (proteksi nyasar,
       berlaku apapun source-nya — test mode aman buat semua akun).
    2. Selain itu → semua route non-test yang enabled dengan source yang sama
       dengan sinyal (route tanpa field 'source' = 'public').
       Multi akun MT5: detektor A (source public) → route publik,
       detektor B (source vip) → route VIP. FANOUT dalam source tetap jalan.
    3. Source 'public' tanpa match → fallback perilaku lama (prod default).
       Source lain tanpa match → KOSONG (sinyal dibuang, BUKAN ke publik —
       anti-bocor; selfbot log jelas).
    Tiap route: {name, chat_id?, account?, source?, test?}.
    """
    cfg = load_telegram_config()
    routes = [r for r in cfg.get("routes", []) if isinstance(r, dict) and r.get("enabled", True)]
    src = _norm_source(sig)
    if sig.get("test"):
        pool = [r for r in routes if r.get("test")]
        if not pool:
            pool = [{"name": "test", "chat_id": TEST_CHAT_ID}]
        return pool
    pool = [r for r in routes if not r.get("test")
            and str(r.get("source") or "public").strip().lower() == src]
    if not pool and src == "public":
        pool = [{"name": "prod"}]
    return pool


def _apply_route(item, route):
    """Tempel chat_id/account/route ke satu item queue."""
    cid = route.get("chat_id")
    if cid:
        try:
            item["chat_id"] = int(cid)
        except (TypeError, ValueError):
            pass
    acc = route.get("account")
    if acc:
        item["account"] = str(acc)
    fmt = str(route.get("format") or "").strip()
    if fmt:
        item["format"] = fmt.lower()
    item["route"] = str(route.get("name") or ("test" if route.get("test") else "prod"))


def _enqueue_fanout(base_item, sig, desc):
    """Fanout satu sinyal ke semua route tujuan (multi channel, per source).

    1 sinyal → N item queue (satu per route). Tiap item bawa route name +
    chat_id (kalau ada) + account pin (kalau ada) — selfbot yang eksekusi.
    Pool kosong (source tanpa route) → sinyal DIBUANG dengan log jelas.
    """
    targets = route_targets(sig or {})
    if not targets:
        log(f"🚫 DROP {desc} — gak ada route enabled untuk source "
            f"'{_norm_source(sig)}' (dibuang, bukan diterusin ke publik)")
        return
    q = load_sb_queue()
    names = []
    for route in targets:
        item = dict(base_item)
        _apply_route(item, route)
        q.append(item)
        names.append(item["route"])
    save_sb_queue(q)
    log(f"📤 ENQUEUE {desc} → {len(names)} route: {', '.join(names)}")


def enqueue_entry(sig):
    base = {
        "type": "ENTRY",
        "symbol": sig.get("symbol"),
        "type_": sig.get("type"),
        "price": sig.get("price"),
        "sl": 0,
        "tp": 0,
        "digits": int(sig.get("digits", 2)),
        "position": sig.get("position"),
        "deal": sig.get("deal"),
        "test": bool(sig.get("test")),
        "ts": time.time(),
    }
    _enqueue_fanout(base, sig, f"ENTRY: {sig.get('type')} {sig.get('symbol')} @ {sig.get('price')}")


def enqueue_notice(text, sig=None):
    """Send system notice to Telegram (non-trade alert)."""
    base = {
        "type": "NOTICE",
        "text": text,
        "test": bool((sig or {}).get("test")),
        "ts": time.time(),
    }
    _enqueue_fanout(base, sig or {}, f"NOTIFICATION: {text[:50]}")


def enqueue_sltp(sig, delay):
    base = {
        "type": "SLTP",
        "symbol": sig.get("symbol"),
        "sl": sig.get("sl"),
        "tp": sig.get("tp"),
        "deal": sig.get("deal"),
        "position": sig.get("position"),
        "test": bool(sig.get("test")),
        "ts": time.time(),
        "send_after": time.time() + delay,
    }
    _enqueue_fanout(base, sig, f"SLTP: {sig.get('symbol')} SL={sig.get('sl')} TP={sig.get('tp')} (+{delay}s)")


def enqueue_limit(sig):
    """Enqueue pesan pending order (BUY LIMIT / SELL LIMIT) ke Telegram."""
    # Baca area range & SL distance dari detector config (source of truth di VPS)
    try:
        dcfg = load_detector_config()
        area_range = float(dcfg.get("settings", {}).get("limit_area_range", 2))
        sl_distance = float(dcfg.get("settings", {}).get("limit_sl_distance", 5))
    except (TypeError, ValueError):
        area_range, sl_distance = 2.0, 5.0

    base = {
        "type": "LIMIT",
        "symbol": sig.get("symbol"),
        "type_": sig.get("type"),
        "price": sig.get("price"),
        "sl": sig.get("sl", 0),
        "tp": sig.get("tp", 0),
        "digits": int(sig.get("digits", 2)),
        "position": sig.get("position"),
        "deal": sig.get("deal"),
        "test": bool(sig.get("test")),
        "area_range": area_range,
        "sl_distance": sl_distance,
        "ts": time.time(),
    }
    _enqueue_fanout(base, sig, f"LIMIT: {sig.get('type')} LIMIT {sig.get('symbol')} @ {sig.get('price')} "
                              f"(area ±{area_range}, SL fallback {sl_distance})")


def send_complete(st, sig):
    """Kirim entry + SL/TP (terpisah kalau ada), set lock active."""
    enqueue_entry(sig)
    if float(sig.get("sl") or 0) > 0 or float(sig.get("tp") or 0) > 0:
        enqueue_sltp(sig, SLTP_GAP_SECONDS)
    st["active"][_active_key(sig)] = {
        "position": sig.get("position"),
        "ts": time.time(),
        "price": sig.get("price"),
        "source": _norm_source(sig),
    }
    log(f"✅ SENT COMPLETE: {sig.get('type')} {sig.get('symbol')} SL={sig.get('sl')} TP={sig.get('tp')}")


def send_entry_only(st, sig):
    """Kirim entry doang (fallback saat grace habis tanpa SL/TP lengkap)."""
    enqueue_entry(sig)
    st["active"][_active_key(sig)] = {
        "position": sig.get("position"),
        "ts": time.time(),
        "price": sig.get("price"),
        "source": _norm_source(sig),
    }
    log(f"⌛ SENT ENTRY-ONLY (grace expired): {sig.get('type')} {sig.get('symbol')}")


# ---- handlers (dipanggil sambil pegang _lock) ----
def on_open(st, d):
    symbol = d.get("symbol")
    position = d.get("position") or 0
    deal = d.get("deal") or 0
    now = time.time()

    # Lock check PER SOURCE: posisi aktif di symbol ini dari AKUN YANG SAMA?
    # Akun lain (source beda) di symbol sama tetep boleh kirim.
    akey = _active_key(d)
    act = st["active"].get(akey)
    if act and (now - act.get("ts", 0)) < STALE_LOCK_SECONDS:
        log(f"🚫 SUPPRESS {akey}: posisi {act.get('position')} masih aktif "
            f"(source {_norm_source(d)})")
        return {"status": "suppressed", "reason": "position_active"}

    sl = float(d.get("sl") or 0)
    tp = float(d.get("tp") or 0)

    # Entry udah bawa SL/TP (detector udah nunggu lengkap/grace) -> kirim sekarang juga
    if sl > 0 or tp > 0:
        send_complete(st, d)
        return {"status": "sent"}

    # BELUM LENGKAP -> KIRIM ENTRY SEKARANG JUGA, SL/TP nyusul terpisah
    enqueue_entry(d)
    st["active"][akey] = {
        "position": position,
        "ts": now,
        "price": d.get("price"),
        "source": _norm_source(d),
        "waiting_sltp": True,  # marker: masih nunggu SL/TP
    }
    log(f"📤 ENTRY sent immediately: {d.get('type')} {akey} @ {d.get('price')} (SLTP pending)")
    return {"status": "sent", "sltp_pending": True}


def on_sltp(st, d):
    symbol = d.get("symbol")
    position = d.get("position") or 0
    deal = d.get("deal") or 0
    sl = float(d.get("sl") or 0)
    tp = float(d.get("tp") or 0)

    # Cari pending entry yang cocok (legacy behavior)
    matched_key = None
    for key, pend in st["pending"].items():
        if pend["symbol"] != symbol:
            continue
        if (deal > 0 and pend.get("deal") == deal) or \
           (position > 0 and pend.get("position") == position):
            matched_key = key
            break

    if matched_key:
        pend = st["pending"][matched_key]
        if sl > 0:
            pend["sl"] = sl
        if tp > 0:
            pend["tp"] = tp

        if not (pend["sl"] > 0 and pend["tp"] > 0):
            log(f"⏳ SLTP partial {symbol} (SL={pend['sl']}, TP={pend['tp']}) — masih nunggu")
            return {"status": "holding_partial"}

        del st["pending"][matched_key]
        send_complete(st, pend)
        return {"status": "sent", "merged": True}

    # TIDAK ADA PENDING -> cari ACTIVE lock dengan source + position yang sama
    akey = _active_key(d)
    act = st["active"].get(akey)
    if act and act.get("position") == position:
        if sl == 0 and tp == 0:
            return {"status": "ignored", "reason": "sltp_zero"}
        # SLTP cuma SEKALI per posisi — geser SL/TP berikutnya diabaikan diam-diam
        if act.get("sltp_sent"):
            log(f"ℹ️ SLTP {symbol} pos {position} diabaikan (sudah pernah dikirim)")
            return {"status": "ignored", "reason": "sltp_already_sent"}
        # Kirim SLTP terpisah (entry udah dikirim duluan)
        sig = {
            "symbol": symbol,
            "type": d.get("type"),
            "sl": sl,
            "tp": tp,
            "digits": d.get("digits", 2),
            "position": position,
            "deal": deal,
            "source": d.get("source"),  # ikut routing per source
        }
        enqueue_sltp(sig, 0)  # kirim langsung, tanpa delay
        act["sltp_sent"] = True
        # Clear waiting marker
        act.pop("waiting_sltp", None)
        log(f"📤 SLTP sent separately: {symbol} SL={sl} TP={tp}")
        return {"status": "sent", "separate": True}

    # Tidak ada pending, tidak ada active yang cocok -> abaikan
    log(f"🚫 SLTP {symbol} pos {position} diabaikan (no pending, no active match)")
    return {"status": "ignored", "reason": "no_pending_entry"}


def on_close(st, d):
    symbol = d.get("symbol")
    position = d.get("position") or 0

    # Lock per source: cuma lepasin lock milik akun yang nge-close
    akey = _active_key(d)
    act = st["active"].get(akey)
    if act and act.get("position") == position:
        del st["active"][akey]
        log(f"🔓 CLOSE {akey} pos {position} — lock dilepas")
    elif act:
        log(f"ℹ️ CLOSE {akey} pos {position} (lock aktif posisi {act.get('position')})")

    # Buang pending untuk posisi ini (close sebelum SL/TP lengkap)
    for key in list(st["pending"].keys()):
        pend = st["pending"][key]
        if pend["symbol"] == symbol and pend.get("position") == position:
            del st["pending"][key]
            log(f"🗑️ Pending {symbol} pos {position} dibuang (closed)")

    return {"status": "closed"}


def on_limit(st, d):
    """Pending order baru (BUY LIMIT / SELL LIMIT) terpasang di MT5.

    Payload dari detector:
        action=LIMIT, type=BUY/SELL, symbol, price (limit price),
        position (order ticket), deal (order ticket), digits.
    """
    symbol = d.get("symbol")
    typ = str(d.get("type") or "BUY").upper()
    position = d.get("position") or d.get("deal") or 0

    if typ not in ("BUY", "SELL"):
        log(f"🚫 LIMIT {symbol} type {typ} tidak dikenal — skip")
        return {"status": "skipped", "reason": f"unknown_type_{typ}"}

    enqueue_limit(d)
    return {"status": "sent", "kind": f"{typ}_LIMIT"}


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
            for akey, info in st.get("active", {}).items():
                if "|" in akey:
                    src, symbol = akey.split("|", 1)
                else:
                    src, symbol = "public", akey
                positions.append({
                    "source": src,
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
            # ?source=vip → config detektor VIP (file terpisah per akun)
            qs = parse_qs(parsed.query)
            source = (qs.get("source", [""])[0] or "").strip().lower()
            cfg = load_detector_config(source)
            if qs.get("mask", ["0"])[0] == "1":
                cfg = json.loads(json.dumps(cfg))
                pw = cfg["mt5"].get("password", "")
                cfg["mt5"]["password"] = ("•" * 8 + pw[-2:]) if pw else ""
            self._json(200, cfg, cors=True)
        
        elif path == "/api/config/detector/checksum":
            # Lightweight endpoint buat detector poll perubahan (no auth body leak)
            qs = parse_qs(parsed.query)
            source = (qs.get("source", [""])[0] or "").strip().lower()
            cfg = load_detector_config(source)
            self._json(200, {
                "version": cfg.get("meta", {}).get("version", 0),
                "checksum": cfg.get("meta", {}).get("checksum", ""),
            }, cors=True)

        # ---- Telegram config (read) ----
        elif path == "/api/config/telegram":
            # Auth required — config mengandung api_hash & nama file session
            secret = self.headers.get("X-Signal-Secret") or self.headers.get("Authorization", "").replace("Bearer ", "")
            if not secret:
                qs = parse_qs(parsed.query)
                secret = qs.get("secret", [None])[0]
            if secret != SECRET:
                return self._json(401, {"error": "unauthorized"}, cors=True)
            qs = parse_qs(parsed.query)
            cfg = load_telegram_config()
            if qs.get("mask", ["0"])[0] == "1":
                cfg = json.loads(json.dumps(cfg))
                for acc in cfg.get("accounts", []):
                    ah = str(acc.get("api_hash", ""))
                    if ah:
                        acc["api_hash"] = "•" * 8 + ah[-4:]
            self._json(200, cfg, cors=True)
        elif path == "/api/config/telegram/checksum":
            # Lightweight endpoint buat selfbot hot-reload
            cfg = load_telegram_config()
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

        # ---- API: Reset system with safety checks (requires auth) ----
        # IMPORTANT: NEVER reset while active positions exist without explicit force flag
        if path == "/api/reset":
            secret = self.headers.get("X-Signal-Secret") or self.headers.get("Authorization", "").replace("Bearer ", "")
            if not secret:
                qs = parse_qs(parsed.query)
                secret = qs.get("secret", [None])[0]
            if secret != SECRET:
                return self._json(401, {"error": "unauthorized"}, cors=True)

            # Check client IP and log for audit trail
            client_ip = self.client_address[0]

            # force=true dari query ATAU body JSON — dulu dijanjikan di pesan
            # error tapi GAK PERNAH dibaca (reset selalu blocked kalau ada posisi)
            qs = parse_qs(parsed.query)
            force = (qs.get("force", [""])[0] or "").strip().lower() in ("1", "true", "yes")
            try:
                _len = int(self.headers.get("Content-Length", 0))
                if _len:
                    _body = json.loads(self.rfile.read(_len).decode('utf-8'))
                    if isinstance(_body, dict) and _body.get("force"):
                        force = True
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
                pass

            with _lock:
                st = load_state()

                # SAFETY CHECK: Don't allow reset if active positions exist
                active_count = len(st.get("active", {}))
                pending_count = len(st.get("pending", {}))

                if active_count > 0 and not force:
                    return self._json(
                        400,
                        {
                            "error": "reset_blocked",
                            "reason": f"Cannot reset: {active_count} active position(s) detected. Close all positions first or use force=true parameter.",
                            "active_positions": list(st["active"].keys()),
                            "pending_orders": pending_count
                        },
                        cors=True
                    )

                # Safe to reset - only pending orders remain
                save_state({"active": {}, "pending": {}})
                save_sb_queue([])
            
            log(f"✅ SYSTEM RESET via API from {client_ip} — {pending_count} pending orders cleared (no active positions)")
            return self._json(200, {
                "status": "reset complete", 
                "cleared_pending": pending_count,
                "cleared_active": 0,
                "source_ip": client_ip
            }, cors=True)
        
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

            qs = parse_qs(parsed.query)
            source = (qs.get("source", [""])[0] or "").strip().lower()
            with _lock:
                cfg = load_detector_config(source)
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
                
                cfg = save_detector_config(cfg, source)
            
            label = f" [{source}]" if source and source != DEFAULT_DETECTOR_SOURCE else ""
            log(f"✅ DETECTOR CONFIG{label} UPDATED (v{cfg['meta']['version']}) — from {self.client_address[0]}")
            return self._json(200, {
                "status": "updated",
                "version": cfg["meta"]["version"],
                "checksum": cfg["meta"]["checksum"]
            }, cors=True)
        
        # ---- Telegram config (write) ----
        elif path == "/api/config/telegram":
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
                cfg = load_telegram_config()
                if "accounts" in req:
                    cfg["accounts"] = req["accounts"]
                if "routes" in req:
                    cfg["routes"] = req["routes"]

                # Validasi basic
                names = set()
                for acc in cfg.get("accounts", []):
                    if not isinstance(acc, dict) or not acc.get("name"):
                        return self._json(400, {"error": "account butuh field 'name'"}, cors=True)
                    if acc["name"] in names:
                        return self._json(400, {"error": f"account duplikat: {acc['name']}"}, cors=True)
                    names.add(acc["name"])
                rnames = set()
                for r in cfg.get("routes", []):
                    if not isinstance(r, dict) or not (r.get("name") or r.get("test")):
                        return self._json(400, {"error": "route butuh field 'name'"}, cors=True)
                    nm = r.get("name") or ("test" if r.get("test") else "prod")
                    if nm in rnames:
                        return self._json(400, {"error": f"route duplikat: {nm}"}, cors=True)
                    rnames.add(nm)
                    pin = r.get("account")
                    if pin and pin not in names:
                        return self._json(400, {"error": f"route '{nm}' pin akun '{pin}' yang tidak ada"}, cors=True)

                cfg = save_telegram_config(cfg)

            log(f"✅ TELEGRAM CONFIG UPDATED (v{cfg['meta']['version']}) — from {self.client_address[0]}")
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
        src = _norm_source(d)

        # dedup per event (source ikut — ticket akun beda bisa kebetulan sama)
        if action == "OPEN":
            dedup_key = ("OPEN", src, d.get("deal"), d.get("position"))
        elif action == "SLTP":
            dedup_key = ("SLTP", src, d.get("symbol"), d.get("position"), d.get("sl"), d.get("tp"))
        elif action == "CLOSE":
            dedup_key = ("CLOSE", src, d.get("position") or d.get("deal"))
        elif action == "LIMIT":
            dedup_key = ("LIMIT", src, d.get("deal") or d.get("position"))
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
            elif action == "LIMIT":
                res = on_limit(st, d)
            elif action == "NOTICE":
                enqueue_notice(d.get("text", ""), d)  # oper payload → flag test ikut
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
