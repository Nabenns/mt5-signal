"""
MT5 Signal Selfbot v8 — Immediate single-message mode.

Format:
- Jika SL=0 & TP=0: "💰 BUY NOW XAUUSD 4820"
- Jika SL > 0 OR TP > 0: "💰 BUY NOW XAUUSD 4820 | SL X | TP Y" (dalam 1 line)

No dual messages. No delay. No waiting for complete SL/TP.
"""

import asyncio
import random
import time
import json
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient
from telethon.tl.functions.messages import SendMessageRequest as SendReq
from telethon.tl.types import MessageEntityCustomEmoji, MessageEntityItalic, MessageEntityBold

SESSION = "/root/mt5-signal/6285196827787.session"
API_ID = 38274094
API_HASH = "c57671be8ccbd29f37dd82c97a28370e"
TG_CHAT_ID = -1004479253024
BUY_EMOJI_ID = 5296596700704548349
SELL_EMOJI_ID = 5294049355601292129

_seen_deals = {}
_seen_lock = asyncio.Lock()
_sb_queue = None

def load_sb_queue():
    try:
        with open('/root/mt5-signal/sb_queue.json') as f:
            return json.load(f)
    except:
        return []

def save_sb_queue(q):
    import os
    tmp = '/root/mt5-signal/sb_queue.json.tmp'
    with open(tmp, 'w') as f:
        json.dump(q, f)
    os.replace(tmp, '/root/mt5-signal/sb_queue.json')


async def flush_once(client):
    """Ambil semua sinyal di queue, kirim satu per satu."""
    global _sb_queue
    _sb_queue = load_sb_queue()
    if not _sb_queue:
        return 0
    
    sent = 0
    for sig in _sb_queue[:]:
        msg_type = sig.get("type", "ENTRY").upper()
        
        # Dedup per deal
        deal = sig.get("deal")
        dedup_key = f"{msg_type}:{deal}" if deal else None
        if dedup_key:
            async with _seen_lock:
                if len(_seen_deals) > 2000:
                    _seen_deals.clear()
                if dedup_key in _seen_deals and time.time() - _seen_deals[dedup_key] < 300:
                    _sb_queue.remove(sig)
                    save_sb_queue(_sb_queue)
                    continue
                _seen_deals[dedup_key] = time.time()
        
        if msg_type == "ENTRY":
            sym = str(sig.get("symbol") or "?").replace("_", "")
            typ = str(sig.get("type_") or "BUY").upper()
            price = sig.get("price", 0)
            sl = sig.get("sl", 0) or 0
            tp = sig.get("tp", 0) or 0
            digits = int(sig.get("digits", 2))
            
            try:
                val = float(price)
                harga = str(int(round(val))) if digits <= 2 else f"{round(val, digits):.{digits}f}"
            except:
                harga = str(price)
            
            # Build message: custom emoji + text
            if typ == "BUY":
                emoji_id = BUY_EMOJI_ID
                base_text = f"\U0001F4B0\u00a0{typ} NOW {sym} {harga}"
                from telethon.tl.types import MessageEntityCustomEmoji, MessageEntityItalic
                entities = [
                    MessageEntityCustomEmoji(offset=0, length=2, document_id=emoji_id),
                    MessageEntityItalic(offset=len(base_text) - len(harga), length=len(harga)),
                ]
            elif typ == "SELL":
                emoji_id = SELL_EMOJI_ID
                base_text = f"\U0001F53D\u00a0{typ} NOW {sym} {harga}"
                from telethon.tl.types import MessageEntityCustomEmoji, MessageEntityItalic
                entities = [
                    MessageEntityCustomEmoji(offset=0, length=2, document_id=emoji_id),
                    MessageEntityItalic(offset=len(base_text) - len(harga), length=len(harga)),
                ]
            else:
                base_text = f"{sym} {harga} {typ}"
                entities = []
            
            # Append SL/TP if exists (in same line)
            full_text = base_text
            if sl > 0 or tp > 0:
                full_text += f" | SL {sl} | TP {tp}"
            
            try:
                entity = await client.get_entity(TG_CHAT_ID)
                await client(SendReq(
                    peer=entity,
                    message=full_text,
                    entities=entities,
                    random_id=random.randrange(-2**63, 2**63),
                ))
                log(f"✅ SENT ({typ}): {sym} {harga}{f' | SL {sl} | TP {tp}' if sl > 0 or tp > 0 else ''}")
                sent += 1
            except Exception as e:
                log(f"❌ GAGAL kirim: {e}")
        
        _sb_queue.remove(sig)
        save_sb_queue(_sb_queue)
        await asyncio.sleep(0.5)
    
    return sent

log_calls = []
def log(msg):
    now_wib = datetime.now(timezone.utc).astimezone(tz=timezone(timedelta(hours=7))).strftime('%H:%M WIB')
    line = f"[{now_wib}] {msg}"
    print(line, flush=True)
    log_calls.append(line)

def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    loop.run_until_complete(client.connect())
    if not loop.run_until_complete(client.is_user_authorized()):
        log("❌ NOT AUTHORIZED!")
        return
    
    user = loop.run_until_complete(client.get_me())
    log(f"✅ Connected as {user.first_name} (ID: {user.id})")
    
    # Startup notice
    try:
        loop.run_until_complete(client(SendReq(peer=TG_CHAT_ID, message="🤖 Signal Relay v8 ONLINE", random_id=random.randrange(-2**63, 2**63))))
        log("Startup notice sent")
    except:
        pass
    
    while True:
        try:
            sent = loop.run_until_complete(flush_once(client))
            if sent == 0:
                time.sleep(2)
        except KeyboardInterrupt:
            log("Shutting down...")
            break
        except Exception as e:
            log(f"Error in main loop: {e}")
            time.sleep(5)
    
    loop.close()
    client.disconnect()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(traceback.format_exc())
