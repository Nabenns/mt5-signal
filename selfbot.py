"""
MT5 Signal Selfbot v10 — consume sb_queue.json, send via user account (Telethon).

Queue item types:
- ENTRY: emoji + "BUY NOW XAUUSD 4820" (custom animated emoji + harga italic)
- SLTP : "SL 4815 | TP 4835" (message terpisah, respect send_after delay)
"""

import asyncio
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
    MessageEntityCustomEmoji,
    MessageEntityItalic,
)

BASE = os.path.dirname(os.path.abspath(__file__))
SESSION = os.path.join(BASE, "6285196827787")  # telethon append .session
API_ID = 38274094
API_HASH = "c57671be8ccbd29f37dd82c97a28370e"
TG_CHAT_ID = -1001816822545  # Production channel: MT5 Signal Relay (New)
TG_TEST_CHAT_ID = -1004479253024  # Test channel (channel lama, buat testing)
SB_QUEUE = os.path.join(BASE, "sb_queue.json")
LOG_FILE = os.path.join(BASE, "selfbot.log")
WIB = timezone(timedelta(hours=7))

BUY_EMOJI_ID = 5296596700704548349   # custom emoji BUY (ijo muter)
SELL_EMOJI_ID = 5294049355601292129  # custom emoji SELL

_seen = {}
_seen_lock = asyncio.Lock()


def target_chat(sig):
    """Channel tujuan dengan PROTEKSI KETAT.

    Rules:
    1. Kalau sig.test == True → SELALU test channel. Gak peduli chat_id
       yang dikirim (proteksi kalau payload nyasar ke prod).
    2. Kalau ada chat_id eksplisit (dari receiver) → pakai itu.
    3. Default → channel PROD.
    """
    if sig.get("test"):
        return TG_TEST_CHAT_ID
    cid = sig.get("chat_id")
    if cid:
        return int(cid)
    return TG_CHAT_ID


def log(msg):
    line = f"[{datetime.now(WIB).strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


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


async def send_entry(client, sig):
    sym = clean_sym(sig.get("symbol"))
    typ = str(sig.get("type_") or sig.get("type") or "BUY").upper()
    digits = int(sig.get("digits", 2))
    harga = fmt_harga(sig.get("price", 0), digits)
    chat = target_chat(sig)

    if typ == "BUY":
        base = f"\U0001F4B0\u00a0{typ} NOW {sym} {harga}"
        emoji_id = BUY_EMOJI_ID
    elif typ == "SELL":
        base = f"\U0001F53D\u00a0{typ} NOW {sym} {harga}"
        emoji_id = SELL_EMOJI_ID
    else:
        base = f"{typ} NOW {sym} {harga}"
        emoji_id = None

    entities = []
    if emoji_id:
        entities.append(MessageEntityCustomEmoji(offset=0, length=2, document_id=emoji_id))

    await client(SendReq(
        peer=await client.get_entity(chat),
        message=base,
        entities=entities,
        random_id=random.randrange(-2**63, 2**63),
    ))
    log(f"✅ SENT ENTRY ({typ}): {sym} {harga} → chat {chat}")


async def send_sltp(client, sig):
    sl = sig.get("sl") or 0
    tp = sig.get("tp") or 0
    digits = int(sig.get("digits", 2))
    chat = target_chat(sig)
    
    parts = []
    if float(sl) > 0:
        parts.append(f"SL {fmt_harga(sl, digits)}")
    if float(tp) > 0:
        parts.append(f"TP {fmt_harga(tp, digits)}")
    if not parts:
        return
    
    text = " | ".join(parts)
    await client(SendReq(
        peer=await client.get_entity(chat),
        message=text,
        random_id=random.randrange(-2**63, 2**63),
    ))
    log(f"✅ SENT SLTP: {text} → chat {chat}")


def _fmt_limit_price(v, digits):
    """Format harga limit untuk area. 4477.4 → '4477', 4477.6 → '4478'."""
    import math
    try:
        val = float(v)
    except (TypeError, ValueError):
        return str(v)
    if digits <= 2:
        return str(int(math.floor(val + 0.5 - 1e-9)))
    return f"{round(val, digits):.{digits}f}"


async def send_limit(client, sig):
    """Kirim pesan pending order (BUY LIMIT / SELL LIMIT) format template user.

    Contoh (BUY LIMIT @ 4477, area 4477-4474, SL 4471):
        💰 BUY XAUUSD | 4477 - 4474
        SL : 4471

        TP 1 : 60 PIPS
        TP 2 : 120 PIPS
        TP 3 : ⁉️

        JAGA RISK KALIAN GUYS ‼️

    Contoh (SELL LIMIT @ 4477, area 4477-4479, SL 4481):
        🔻 SELL XAUUSD | 4477 - 4479
        SL : 4481
        (template TP & footer sama)
    """
    sym = clean_sym(sig.get("symbol"))
    typ = str(sig.get("type_") or sig.get("type") or "BUY").upper()
    digits = int(sig.get("digits", 2))
    chat = target_chat(sig)

    price = sig.get("price") or 0
    area_range = float(sig.get("area_range", 2))
    sl_dist = float(sig.get("sl_distance", 5))

    # Harga utama (limit price) & batas area
    base = float(price)
    if typ == "BUY":
        # BUY LIMIT: area DI BAWAH harga (price .. price-area), SL di bawah lagi
        price_high = _fmt_limit_price(base, digits)
        price_low = _fmt_limit_price(base - area_range, digits)
        sl_price = sig.get("sl") or (base - sl_dist)
    else:
        # SELL LIMIT: area DI ATAS harga (price .. price+area), SL di atas lagi
        price_high = _fmt_limit_price(base + area_range, digits)
        price_low = _fmt_limit_price(base, digits)
        sl_price = sig.get("sl") or (base + sl_dist)

    header = f"| {price_high} - {price_low}"

    if typ == "BUY":
        head_icon = "\U0001F4B0"  # 💰
        emoji_id = BUY_EMOJI_ID
    else:
        head_icon = "\U0001F53D"  # 🔻
        emoji_id = SELL_EMOJI_ID

    text = (
        f"{head_icon} {typ} {sym} {header}\n"
        f"SL : {_fmt_limit_price(sl_price, digits)}\n\n"
        f"TP 1 : 60 PIPS\n"
        f"TP 2 : 120 PIPS\n"
        f"TP 3 : \u2049\ufe0f\n\n"
        f"JAGA RISK KALIAN GUYS \u203c\ufe0f"
    )

    # Custom emoji BUY/SELL di posisi awal (2 char) — sama seperti send_entry
    entities = [MessageEntityCustomEmoji(offset=0, length=2, document_id=emoji_id)]

    await client(SendReq(
        peer=await client.get_entity(chat),
        message=text,
        entities=entities,
        random_id=random.randrange(-2**63, 2**63),
    ))
    log(f"✅ SENT LIMIT ({typ}): {sym} {price_high}-{price_low} SL {sl_price} → chat {chat}")


async def flush_once(client):
    q = load_queue()
    if not q:
        return 0
    
    sent = 0
    for sig in q[:]:
        send_after = sig.get("send_after")
        if send_after and time.time() < send_after:
            continue
        
        key = f"{sig.get('type')}:{sig.get('deal') or sig.get('position')}"
        async with _seen_lock:
            if len(_seen) > 2000:
                _seen.clear()
            now = time.time()
            if key in _seen and now - _seen[key] < 300:
                q.remove(sig)
                save_queue(q)
                continue
            _seen[key] = now
        
        try:
            if sig.get("type") == "SLTP":
                await send_sltp(client, sig)
            elif sig.get("type") == "LIMIT":
                await send_limit(client, sig)
            elif sig.get("type") == "NOTICE":
                # Send system notice as plain text (no emoji)
                text = sig.get("text", "")
                if text:
                    entities = []
                    await client(SendReq(
                        peer=await client.get_entity(target_chat(sig)),
                        message=text,
                        entities=entities,
                        random_id=random.randrange(-2**63, 2**63),
                    ))
                    log(f"✅ SENT NOTICE: {text[:80]} → chat {target_chat(sig)}")
            else:
                await send_entry(client, sig)
        except FloodWaitError as e:
            log(f"⏳ FloodWait {e.seconds}s — retry nanti")
            break
        except Exception as e:
            log(f"❌ GAGAL kirim: {e}")
            break
        
        q.remove(sig)
        save_queue(q)
        await asyncio.sleep(0.5)
    return sent


async def main():
    log("Selfbot v10 start")
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        log("❌ Session tidak authorized! Jalankan python3 login.py dulu.")
        return
    me = await client.get_me()
    log(f"✅ Connected as {me.first_name} (ID: {me.id})")

    while True:
        try:
            if await flush_once(client) == 0:
                await asyncio.sleep(1)
        except Exception as e:
            log(f"⚠️ Error loop: {e}")
            await asyncio.sleep(5)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("👋 Shutdown")
