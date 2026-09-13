"""
MT5 Signal Selfbot v11 — multi akun + multi channel (consume sb_queue.json, Telethon).

Konsep:
- telegram_config.json (sebelah file ini) = source of truth: daftar accounts
  (session Telethon + api_id/api_hash) dan routes (channel tujuan).
- Receiver fanout: 1 sinyal → N item queue, satu per route. Tiap item bawa
  "route" (nama), "chat_id" (kalau receiver tahu), "account" (pin, opsional).
- Selfbot: satu TelegramClient per akun enabled. Route yang pin akun dipakai
  akun itu dulu; selain itu akun sehat pertama (default). FloodWait/error
  → failover otomatis ke akun enabled berikutnya.
- Hot-reload: config di-poll per mtime; akun baru konek, akun dihapus di-disconnect,
  tanpa restart service.
- Fallback: tanpa config (atau tanpa akun enabled) → perilaku lama v10
  (session legacy 6285196827787, PROD/TEST hardcode).

Queue item types:
- ENTRY: emoji + "BUY NOW XAUUSD 4820" (custom animated emoji + harga italic)
- SLTP : "SL 4815 | TP 4835" (message terpisah, respect send_after delay)
- LIMIT: template pending order, NOTICE: plain text
"""

import asyncio
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SendMessageRequest as SendReq
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityCustomEmoji,
    MessageEntityItalic,
)

BASE = os.path.dirname(os.path.abspath(__file__))
TG_CONFIG_FILE = os.path.join(BASE, "telegram_config.json")
SB_QUEUE = os.path.join(BASE, "sb_queue.json")
LOG_FILE = os.path.join(BASE, "selfbot.log")
HEALTH_FILE = os.path.join(BASE, "selfbot_health.json")
WIB = timezone(timedelta(hours=7))

# ---- fallback legacy (dipakai cuma kalau telegram_config.json kosong/tanpa akun) ----
LEGACY_SESSION = os.path.join(BASE, "6285196827787")  # telethon append .session
LEGACY_API_ID = 38274094
LEGACY_API_HASH = "c57671be8ccbd29f37dd82c97a28370e"
TG_CHAT_ID = -1001816822545       # Production channel: MT5 Signal Relay (New)
TEST_CHAT_ID = -1004479253024   # test channel (channel lama, fallback)


CONFIG_POLL_SECONDS = 5
FLOOD_CAP_SECONDS = 6 * 3600

BUY_EMOJI_ID = 5296596700704548349   # custom emoji BUY (ijo muter)
SELL_EMOJI_ID = 5294049355601292129  # custom emoji SELL

_seen = {}
_seen_lock = asyncio.Lock()


def log(msg):
    line = f"[{datetime.now(WIB).strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------- config ----
class Account:
    """Satu akun Telegram selfbot (session Telethon sendiri)."""

    def __init__(self, cfg):
        self.name = str(cfg.get("name") or "legacy")
        self.enabled = bool(cfg.get("enabled", True))
        self.default = bool(cfg.get("default", False))
        sess = cfg.get("session") or f"tg_{re.sub(r'[^a-zA-Z0-9_-]+', '_', self.name)}"
        self.session = sess if os.path.isabs(sess) else os.path.join(BASE, sess)
        self.api_id = int(cfg.get("api_id") or LEGACY_API_ID)
        self.api_hash = str(cfg.get("api_hash") or LEGACY_API_HASH)
        self.client: "TelegramClient | None" = None
        self.entity_cache = {}       # chat_id -> peer entity
        self.flood_until = 0.0
        self.last_error: "str | None" = None
        self.sent_count = 0
        self.err_count = 0

    def is_flooded(self):
        return time.time() < self.flood_until

    async def ensure_client(self):
        if self.client is None:
            self.client = TelegramClient(self.session, self.api_id, self.api_hash)
        if not self.client.is_connected():
            await self.client.connect()
        return await self.client.is_user_authorized()

    async def get_peer(self, chat_id):
        ent = self.entity_cache.get(chat_id)
        if ent is not None:
            return ent
        ent = await self.client.get_entity(chat_id)
        self.entity_cache[chat_id] = ent
        return ent

    async def send(self, chat_id, text, entities=None):
        await self.client(SendReq(
            peer=await self.get_peer(chat_id),
            message=text,
            entities=entities or [],
            random_id=random.randrange(-2 ** 63, 2 ** 63),
        ))
        self.sent_count += 1

    async def close(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.entity_cache = {}

    def status(self):
        return {
            "name": self.name,
            "enabled": self.enabled,
            "default": self.default,
            "connected": bool(self.client is not None and self.client.is_connected()),
            "flooded_until": self.flood_until if self.is_flooded() else None,
            "sent_count": self.sent_count,
            "err_count": self.err_count,
            "last_error": self.last_error,
        }


def load_tg_config():
    try:
        with open(TG_CONFIG_FILE) as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def build_accounts(cfg):
    accs = [Account(a) for a in cfg.get("accounts", []) if isinstance(a, dict)]
    accs = [a for a in accs if a.enabled]
    if not accs:
        # Fallback legacy v10: satu akun hardcode, perilaku sama persis
        accs = [Account({"name": "legacy", "session": LEGACY_SESSION,
                         "api_id": LEGACY_API_ID, "api_hash": LEGACY_API_HASH,
                         "default": True})]
    return accs


def write_health(accounts):
    try:
        data = {
            "updated_at": time.time(),
            "config_version": (load_tg_config().get("meta", {}) or {}).get("version", 0),
            "accounts": [a.status() for a in accounts],
        }
        tmp = HEALTH_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, HEALTH_FILE)
    except (OSError, TypeError, ValueError):
        pass


# ---------------------------------------------------------------- queue ----
def load_queue():
    try:
        with open(SB_QUEUE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_queue(q):
    tmp = SB_QUEUE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(q, f)
    os.replace(tmp, SB_QUEUE)


def resolve_chat(account, sig):
    """Chat tujuan satu item. Prioritas: chat_id eksplisit dari receiver/route
    → flag test (TEST channel) → default PROD."""
    cid = sig.get("chat_id")
    if cid:
        return int(cid)
    if sig.get("test"):
        return TEST_CHAT_ID
    return TG_CHAT_ID


def mark_flood(account, seconds):
    account.flood_until = time.time() + min(int(seconds), FLOOD_CAP_SECONDS)
    log(f"⏳ {account.name} FloodWait {seconds}s — dilewati sampai "
        f"{datetime.fromtimestamp(account.flood_until, WIB).strftime('%H:%M:%S')}")


def route_format(sig):
    """Nama template format untuk item ini (dari route, default 'default')."""
    return str(sig.get("format") or "default").strip().lower()


# ------------------------------------------------------------- formatting ----
def bulatin(price, digits):
    try:
        val = float(price)
    except (TypeError, ValueError):
        return str(price)
    if digits <= 2:
        return str(int(round(val)))
    return f"{round(val, digits):.{digits}f}"


def clean_sym(s):
    """Bersihin prefix/suffix broker: #BTCUSD → BTCUSD, XAUUSDm → XAUUSD."""
    s = str(s or "?")
    s = re.sub(r'^[#_.\-]+', '', s)
    s = re.sub(r'[._\-]?(m|a|b)\d*$', '', s, flags=re.I)
    return s.upper() or "?"


def fmt_harga(v, digits):
    """Format harga. Harga besar (>=100) dibuletin: .1-.5 turun, .6-.9 naik.
    63010.148 → 63.010 | 63009.627 → 63.010 | 4000.5 → 4.000 | 1.08352 → 1,08352."""
    import math
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)

    if abs(v) >= 100:
        # round half down: 0.1-0.5 → turun, 0.6-0.9 → naik
        rounded = int(math.floor(v + 0.5 - 1e-9))
        return f"{rounded:,}".replace(",", ".")

    # harga kecil (forex): pertahankan desimal, koma sebagai desimal
    s = f"{v:,.{digits}f}"
    s = s.replace(".", "X").replace(",", ".").replace("X", ",")
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def _pip_size(price, digits):
    """Ukuran 1 pip dalam satuan harga.

    - Forex 5 digit (1.08352)        → 0.0001
    - Gold 3 digit (4530.000)        → 0.1   (60 pips = 6.0)
    - JPY 3 digit (109.123)          → 0.01
    - BTC/index 2 digit (63000.00)   → 1.0
    """
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = 0
    if digits >= 5:
        return 0.0001
    if digits == 4:
        return 0.001 if price >= 1000 else 0.0001
    if digits == 3:
        return 0.1 if price >= 1000 else 0.01
    return 1.0 if price >= 1000 else 0.01


def _u16(text, pos):
    """Posisi UTF-16 (unit Telegram) dari index string Python.
    Emoji astral (🔤💰🔻) = 1 char Python tapi 2 unit UTF-16 — entity
    offset/length MTProto wajib unit UTF-16, kalau tidak bold geser."""
    return len(text[:pos].encode("utf-16-le")) // 2


async def send_entry(account, sig):
    if route_format(sig) == "run50":
        return await send_entry_run50(account, sig)
    if route_format(sig) == "indi":
        return await send_entry_indi(account, sig)
    sym = clean_sym(sig.get("symbol"))
    typ = str(sig.get("type_") or sig.get("type") or "BUY").upper()
    digits = int(sig.get("digits", 2))
    harga = fmt_harga(sig.get("price", 0), digits)
    chat = resolve_chat(account, sig)

    # Zone area + SL auto 60 pips (SAMA PERSIS kaya LIMIT)
    base = float(sig.get("price") or 0)
    area_range = float(sig.get("area_range", 2))
    sl_actual = float(sig.get("sl") or 0)
    auto_sl = base + _pip_size(base, digits) * 60 if typ == "SELL" else base - _pip_size(base, digits) * 60
    sl_price = sl_actual if sl_actual > 0 else auto_sl

    if typ == "BUY":
        price_high = fmt_harga(base, digits)
        price_low = fmt_harga(base - area_range, digits)
        header = f"| {price_high} - {price_low}"   # | 4.600 - 4.598
        head_icon = "\U0001F4B0"  # 💰
        emoji_id = BUY_EMOJI_ID
    elif typ == "SELL":
        price_low = fmt_harga(base, digits)
        price_high = fmt_harga(base + area_range, digits)
        header = f"| {price_low} - {price_high}"   # | 4.594 - 4.596
        head_icon = "\U0001F53D"  # 🔻
        emoji_id = SELL_EMOJI_ID
    else:
        header = f"| {harga}"
        head_icon = ""
        emoji_id = None

    text = (
        f"{head_icon} {typ} NOW {sym} {header}\n"
        f"SL : {fmt_harga(sl_price, digits)}\n\n"
        f"TP 1 : 60 PIPS\n"
        f"TP 2 : 120 PIPS\n"
        f"TP 3 : \u2049\ufe0f"
    )

    entities = []
    if emoji_id:
        entities.append(MessageEntityCustomEmoji(offset=0, length=2, document_id=emoji_id))

    # Bold zone + SL — offset/length wajib unit UTF-16 (emoji 💰/🔻 astral)
    hdr_start = text.find(header)
    if hdr_start >= 0:
        entities.append(MessageEntityBold(offset=_u16(text, hdr_start),
                                          length=_u16(text, hdr_start + len(header)) - _u16(text, hdr_start)))
    sl_str = fmt_harga(sl_price, digits)
    sl_start = text.find(f"SL : {sl_str}")
    if sl_start >= 0:
        entities.append(MessageEntityBold(offset=_u16(text, sl_start + 5),
                                          length=_u16(text, sl_start + 5 + len(sl_str)) - _u16(text, sl_start + 5)))

    await account.send(chat, text, entities)
    log(f"✅ SENT ENTRY ({typ}): {sym} {header} SL {fmt_harga(sl_price, digits)} "
        f"→ chat {chat} via {account.name}")


# Custom emoji run50 — varian A (pilihan user, persis pesan referensi DM
# @kokomelonsss): badge BUY/SELL + emoji kedua, lalu ‼️ custom di penutup.
RUN50_BUY_BADGE = 6150042827389670840    # badge BUY (🔤 pertama, varian A)
RUN50_SELL_BADGE = 6149714670413419541   # badge SELL (🔤 pertama, varian A)
RUN50_EMOJI_2_BUY = 6151933897195130910  # 🔤 kedua utk BUY
RUN50_EMOJI_2_SELL = 6149846929636331982 # 🔤 kedua utk SELL
RUN50_EXCL = 5440660757194744323         # ‼️ custom di baris penutup

async def send_entry_run50(account, sig):
    """Format run50 — varian A (pilihan user): badge 🔤🔤 2 emoji custom
    (doc dari pesan referensi DM @kokomelonsss), zona harga + SL bold,
    TP 2 baris, penutup 'RUN 50 PIPS SET BE, JAGA RISK MANAGEMENT ‼️'."""
    sym = clean_sym(sig.get("symbol"))
    typ = str(sig.get("type_") or sig.get("type") or "BUY").upper()
    digits = int(sig.get("digits", 2))
    chat = resolve_chat(account, sig)

    base = float(sig.get("price") or 0)
    area_range = float(sig.get("area_range", 2))
    sl_actual = float(sig.get("sl") or 0)
    auto_sl = base + _pip_size(base, digits) * 60 if typ == "SELL" else base - _pip_size(base, digits) * 60
    sl_price = sl_actual if sl_actual > 0 else auto_sl

    is_buy = typ != "SELL"  # fallback non-BUY/SELL pakai badge BUY
    badge = RUN50_BUY_BADGE if is_buy else RUN50_SELL_BADGE
    emoji2 = RUN50_EMOJI_2_BUY if is_buy else RUN50_EMOJI_2_SELL

    if typ == "BUY":
        price_high = fmt_harga(base, digits)
        price_low = fmt_harga(base - area_range, digits)
        header = f"| {price_high} - {price_low}"
    elif typ == "SELL":
        price_low = fmt_harga(base, digits)
        price_high = fmt_harga(base + area_range, digits)
        header = f"| {price_low} - {price_high}"
    else:
        header = f"| {fmt_harga(base, digits)}"

    # 🔤🔤 dirender via custom emoji (fallback unicode kalau viewer gak load).
    text = (
        f"🔤🔤 {typ} NOW {sym} {header}\n"
        f"SL : {fmt_harga(sl_price, digits)}\n\n"
        f"TP 1 : 60 PIPS\n"
        f"TP 2 : 120 PIPS\n\n"
        f"RUN 50 PIPS SET BE, JAGA RISK MANAGEMENT ‼️"
    )

    entities = [
        # 🔤 astral = 2 unit UTF-16 → offset 0 & 2, length 2 (length 1 = di-strip server)
        MessageEntityCustomEmoji(offset=0, length=2, document_id=badge),
        MessageEntityCustomEmoji(offset=2, length=2, document_id=emoji2),
    ]
    # Bold zona harga + nilai SL — offset UTF-16
    hdr_start = text.find(header)
    if hdr_start >= 0:
        entities.append(MessageEntityBold(offset=_u16(text, hdr_start),
                                          length=_u16(text, hdr_start + len(header)) - _u16(text, hdr_start)))
    sl_str = fmt_harga(sl_price, digits)
    sl_start = text.find(f"SL : {sl_str}")
    if sl_start >= 0:
        entities.append(MessageEntityBold(offset=_u16(text, sl_start + 5),
                                          length=_u16(text, sl_start + 5 + len(sl_str)) - _u16(text, sl_start + 5)))
    tail = "RUN 50 PIPS SET BE, JAGA RISK MANAGEMENT"
    tail_start = text.find(tail + " ‼️")
    if tail_start >= 0:
        entities.append(MessageEntityCustomEmoji(offset=_u16(text, tail_start + len(tail) + 1),
                                                 length=2, document_id=RUN50_EXCL))
    await account.send(chat, text, entities)
    log(f"✅ SENT ENTRY run50 ({typ}): {sym} {header} SL {fmt_harga(sl_price, digits)} "
        f"→ chat {chat} via {account.name}")


# Custom emoji format "indikatorisme" — dari pesan referensi DM @kokomelonsss
# (msg 1815/1816): badge 📈 (BUY) / 📉 (SELL), penutup JANGAN LUPA ATUR... ‼️.
INDI_BUY_BADGE = 5262747715552438702     # 📈 custom
INDI_SELL_BADGE = 5262828387923158890    # 📉 custom
INDI_EXCL = 5440660757194744323          # ‼️ custom (sama dgn run50)


async def send_entry_indi(account, sig):
    """Format 'indikatorisme': badge 📈/📉 1 emoji custom, TP tanpa nomor
    (TP : 60 PIPS / TP : 120 PIPS), penutup 'JANGAN LUPA ATUR RISK
    MANAGEMENT ‼️'. Zona harga + SL bold — offset UTF-16."""
    sym = clean_sym(sig.get("symbol"))
    typ = str(sig.get("type_") or sig.get("type") or "BUY").upper()
    digits = int(sig.get("digits", 2))
    chat = resolve_chat(account, sig)

    base = float(sig.get("price") or 0)
    area_range = float(sig.get("area_range", 2))
    sl_actual = float(sig.get("sl") or 0)
    auto_sl = base + _pip_size(base, digits) * 60 if typ == "SELL" else base - _pip_size(base, digits) * 60
    sl_price = sl_actual if sl_actual > 0 else auto_sl

    is_buy = typ != "SELL"
    badge = INDI_BUY_BADGE if is_buy else INDI_SELL_BADGE
    badge_char = "\U0001F4C8" if is_buy else "\U0001F4C9"

    if typ == "BUY":
        price_high = fmt_harga(base, digits)
        price_low = fmt_harga(base - area_range, digits)
        header = f"| {price_high} - {price_low}"
    elif typ == "SELL":
        price_low = fmt_harga(base, digits)
        price_high = fmt_harga(base + area_range, digits)
        header = f"| {price_low} - {price_high}"
    else:
        header = f"| {fmt_harga(base, digits)}"

    text = (
        f"{badge_char} {typ} NOW {sym} {header}\n"
        f"SL : {fmt_harga(sl_price, digits)}\n\n"
        f"TP : 60 PIPS\n"
        f"TP : 120 PIPS\n\n"
        f"JANGAN LUPA ATUR RISK MANAGEMENT ‼️"
    )

    entities = [
        # 📈/📉 astral = 2 unit UTF-16 → length wajib 2
        MessageEntityCustomEmoji(offset=0, length=2, document_id=badge),
    ]
    hdr_start = text.find(header)
    if hdr_start >= 0:
        entities.append(MessageEntityBold(offset=_u16(text, hdr_start),
                                          length=_u16(text, hdr_start + len(header)) - _u16(text, hdr_start)))
    sl_str = fmt_harga(sl_price, digits)
    sl_start = text.find(f"SL : {sl_str}")
    if sl_start >= 0:
        entities.append(MessageEntityBold(offset=_u16(text, sl_start + 5),
                                          length=_u16(text, sl_start + 5 + len(sl_str)) - _u16(text, sl_start + 5)))
    tail = "JANGAN LUPA ATUR RISK MANAGEMENT"
    tail_start = text.find(tail + " ‼️")
    if tail_start >= 0:
        entities.append(MessageEntityCustomEmoji(offset=_u16(text, tail_start + len(tail) + 1),
                                                 length=2, document_id=INDI_EXCL))
    await account.send(chat, text, entities)
    log(f"✅ SENT ENTRY indi ({typ}): {sym} {header} SL {fmt_harga(sl_price, digits)} "
        f"→ chat {chat} via {account.name}")


async def send_sltp(account, sig):
    sl = sig.get("sl") or 0
    tp = sig.get("tp") or 0
    digits = int(sig.get("digits", 2))
    chat = resolve_chat(account, sig)

    parts = []
    if float(sl) > 0:
        parts.append(f"SL {fmt_harga(sl, digits)}")
    if float(tp) > 0:
        parts.append(f"TP {fmt_harga(tp, digits)}")
    if not parts:
        return

    text = " | ".join(parts)
    # Bold semua harga (SL & TP)
    entities = []
    offset = 0
    for part in parts:
        label, _, val = part.partition(" ")
        price_start = text.find(val, offset)
        if price_start >= 0:
            entities.append(MessageEntityBold(offset=price_start, length=len(val)))
            offset = price_start + len(val)

    await account.send(chat, text, entities)
    log(f"✅ SENT SLTP: {text} → chat {chat} via {account.name}")


def _fmt_limit_price(v, digits):
    """Format harga limit untuk area. 4530.000 → '4530', 4477.6 → '4478'."""
    import math
    try:
        val = float(v)
    except (TypeError, ValueError):
        return str(v)
    if digits <= 2:
        return str(int(math.floor(val + 0.5 - 1e-9)))
    s = f"{round(val, digits):.{digits}f}"
    # Hapus trailing nol: 4530.000 → 4530, 4530.500 → 4530.5
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


async def send_limit(account, sig):
    """Kirim pesan pending order (BUY LIMIT / SELL LIMIT)."""
    sym = clean_sym(sig.get("symbol"))
    typ = str(sig.get("type_") or sig.get("type") or "BUY").upper()
    digits = int(sig.get("digits", 2))
    chat = resolve_chat(account, sig)

    price = sig.get("price") or 0
    area_range = float(sig.get("area_range", 2))
    sl_dist = float(sig.get("sl_distance", 5))

    # Harga utama (limit price) & batas area
    base = float(price)
    sl_actual = float(sig.get("sl") or 0)
    # SL OTOMATIS: total 60 pips dari limit price (SELALU, abaikan sl_distance)
    auto_sl = base + _pip_size(base, digits) * 60 if typ == "SELL" else base - _pip_size(base, digits) * 60
    if typ == "BUY":
        # BUY LIMIT: zone DI BAWAH harga (price-area sampai price), tampil high-low
        price_high = fmt_harga(base, digits)
        price_low = fmt_harga(base - area_range, digits)
        # SL ASLI dari MT5 kalau ada; fallback auto 60 pips
        sl_price = sl_actual if sl_actual > 0 else auto_sl
        header = f"| {price_high} - {price_low}"   # 4.477 - 4.475
    else:
        # SELL LIMIT: zone DI ATAS harga (price sampai price+area), tampil low-high
        price_low = fmt_harga(base, digits)
        price_high = fmt_harga(base + area_range, digits)
        # SL ASLI dari MT5 kalau ada; fallback auto 60 pips
        sl_price = sl_actual if sl_actual > 0 else auto_sl
        header = f"| {price_low} - {price_high}"   # 4.594 - 4.596

    if typ == "BUY":
        head_icon = "\U0001F4B0"  # 💰
        emoji_id = BUY_EMOJI_ID
    else:
        head_icon = "\U0001F53D"  # 🔻
        emoji_id = SELL_EMOJI_ID

    text = (
        f"{head_icon} {typ} LIMIT {sym} {header}\n"
        f"SL : {fmt_harga(sl_price, digits)}\n\n"
        f"TP 1 : 60 PIPS\n"
        f"TP 2 : 120 PIPS\n"
        f"TP 3 : \u2049\ufe0f"
    )
    # Custom emoji BUY/SELL di posisi awal (2 char) — sama seperti send_entry
    entities = []
    entities.append(MessageEntityCustomEmoji(offset=0, length=2, document_id=emoji_id))

    # Bold harga: header area (price_high - price_low) + SL
    hdr_start = text.find(header)
    if hdr_start >= 0:
        entities.append(MessageEntityBold(offset=hdr_start, length=len(header)))
    sl_str = fmt_harga(sl_price, digits)
    sl_start = text.find(f"SL : {sl_str}")
    if sl_start >= 0:
        entities.append(MessageEntityBold(offset=sl_start + 5, length=len(sl_str)))

    await account.send(chat, text, entities)
    log(f"✅ SENT LIMIT ({typ}): {sym} {header} SL {fmt_harga(sl_price, digits)} "
        f"→ chat {chat} via {account.name}")


# ------------------------------------------------------------- sending ----
async def send_via_pool(accounts, sig, sender):
    """Kirim satu item lewat pool akun dengan failover.

    Urutan coba: akun yang di-pin item (kalau ada & sehat) → akun default →
    sisanya. FloodWait menandai akun (dilewati sementara), error lain dihitung.
    Return (True, account) kalau ada yang sukses, (False, None) kalau semua gagal.
    """
    pool = [a for a in accounts if a.enabled and not a.is_flooded()]
    if not pool:
        return False, None
    pin = sig.get("account")

    def prio(acc):
        if pin and acc.name == pin:
            return 0
        if acc.default:
            return 1
        return 2

    pool.sort(key=prio)  # stable: urutan asli dipertahankan dalam prioritas sama

    last_err = None
    for acc in pool:
        try:
            if not await acc.ensure_client():
                raise RuntimeError("session tidak authorized")
            await sender(acc, sig)
            return True, acc
        except FloodWaitError as e:
            mark_flood(acc, e.seconds)
            last_err = e
            continue
        except Exception as e:
            acc.err_count += 1
            acc.last_error = str(e)[:200]
            log(f"❌ {acc.name} gagal kirim: {e}")
            last_err = e
            continue
    if last_err is not None:
        log(f"❌ SEMUA akun gagal ({len(pool)} dicoba): {last_err}")
    return False, None


async def flush_once(accounts):
    q = load_queue()
    if not q:
        return 0

    for sig in q[:]:
        send_after = sig.get("send_after")
        if send_after and time.time() < send_after:
            continue

        # Dedup INCLUDE route — kalau tidak, fanout item ke-2 langsung kebuang.
        # NOTICE gak punya deal/position → tambah hash teks biar notice beda
        # gak saling makan dalam jendela dedup.
        route = sig.get("route") or ("test" if sig.get("test") else "prod")
        key = f"{sig.get('type')}:{sig.get('deal') or sig.get('position')}:{route}"
        if sig.get("type") == "NOTICE":
            key += ":" + hashlib.md5(str(sig.get("text", "")).encode()).hexdigest()[:8]
        async with _seen_lock:
            if len(_seen) > 2000:
                _seen.clear()
            now = time.time()
            if key in _seen and now - _seen[key] < 300:
                log(f"🗑️ SKIP dup {key} (sudah terkirim <5m)")
                q.remove(sig)
                save_queue(q)
                continue
            _seen[key] = now

        typ = sig.get("type")
        if typ == "SLTP":
            async def sender(acc, s):
                await send_sltp(acc, s)
        elif typ == "LIMIT":
            async def sender(acc, s):
                await send_limit(acc, s)
        elif typ == "NOTICE":
            async def sender(acc, s):
                text = s.get("text", "")
                if text:
                    chat = resolve_chat(acc, s)
                    await acc.send(chat, text, [])
                    log(f"✅ SENT NOTICE: {text[:80]} → chat {chat} via {acc.name}")
        else:
            async def sender(acc, s):
                await send_entry(acc, s)

        ok, acc = await send_via_pool(accounts, sig, sender)
        if not ok:
            break  # biarkan item di queue, dicoba lagi flush berikutnya

        q.remove(sig)
        save_queue(q)
        await asyncio.sleep(0.5)
    return 1


async def config_watcher(accounts_holder):
    """Poll telegram_config.json; rebuild accounts kalau file berubah."""
    last_mtime = None
    while True:
        try:
            mtime = os.path.getmtime(TG_CONFIG_FILE) if os.path.exists(TG_CONFIG_FILE) else None
            if mtime != last_mtime:
                if last_mtime is not None:
                    log("🔄 telegram_config.json berubah — reload akun...")
                cfg = load_tg_config()
                new_accounts = build_accounts(cfg)
                old_by_name = {a.name: a for a in accounts_holder[0]}
                for a in new_accounts:
                    prev = old_by_name.get(a.name)
                    if prev is not None and prev.session == a.session and prev.api_id == a.api_id and prev.api_hash == a.api_hash:
                        a.client = prev.client          # pindahkan client yang udah konek
                        a.entity_cache = prev.entity_cache
                        a.flood_until = prev.flood_until
                        a.sent_count = prev.sent_count
                        a.err_count = prev.err_count
                        a.last_error = prev.last_error
                removed = [a for a in accounts_holder[0] if a.name not in {x.name for x in new_accounts}]
                for a in removed:
                    await a.close()
                    log(f"🔌 Akun '{a.name}' dihapus dari config — disconnect")
                accounts_holder[0] = new_accounts
                last_mtime = mtime
                names = ", ".join(a.name for a in new_accounts)
                log(f"👥 Akun aktif: {names}")
                write_health(new_accounts)
        except Exception as e:
            log(f"⚠️ config_watcher: {e}")
        await asyncio.sleep(CONFIG_POLL_SECONDS)


async def health_reporter(accounts_holder):
    while True:
        await asyncio.sleep(30)
        write_health(accounts_holder[0])


async def main():
    log("Selfbot v11 start (multi akun + multi channel)")
    cfg = load_tg_config()
    accounts_holder = [build_accounts(cfg)]

    # Konek awal semua akun
    for acc in accounts_holder[0]:
        try:
            auth = await acc.ensure_client()
            if auth:
                me = await acc.client.get_me()
                log(f"✅ Akun '{acc.name}' connected as {me.first_name} (ID: {me.id})")
            else:
                acc.last_error = "session tidak authorized (jalankan login.py)"
                log(f"❌ Akun '{acc.name}': session tidak authorized! Jalankan python3 login.py dulu.")
        except Exception as e:
            acc.last_error = str(e)[:200]
            log(f"❌ Akun '{acc.name}' gagal konek: {e}")
    write_health(accounts_holder[0])

    asyncio.create_task(config_watcher(accounts_holder))
    asyncio.create_task(health_reporter(accounts_holder))

    while True:
        try:
            await flush_once(accounts_holder[0])
            await asyncio.sleep(1)
        except Exception as e:
            log(f"⚠️ Error loop: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("👋 Shutdown")
