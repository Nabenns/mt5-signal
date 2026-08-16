#!/usr/bin/env python3
"""
MT5 Signal Selfbot - Telegram User Client via MTProto (Telethon)
Setup guide: Run this once to authenticate and start sending signals.
"""

import os
import sys
import asyncio
from datetime import datetime, timezone, timedelta
from telethon import TelegramClient, events

# Config
API_ID = int(os.environ.get('TG_API_ID', 0))
API_HASH = os.environ.get('TG_API_HASH', '')
PHONE_NUMBER = os.environ.get('TG_PHONE_NUMBER', '+628999999999')
TG_CHAT_ID = "-1004479253024"  # Channel target "KingBOB and DUKUN CRYPTO"
SECRET = "3e0371e7c5673317fc134f192e0b7df4dc7a980e8b4fb610"
SESSION_FILE = f"/root/mt5-signal/{PHONE_NUMBER.replace('+','')}.session"

def log(msg):
    print(f"[{datetime.now(timezone.utc).astimezone(tz=timezone(timedelta(hours=7))).strftime('%H:%M:%S')}] {msg}")

async def send_signal(client, signal_data):
    """Kirim sinyal ke Telegram."""
    action = signal_data.get("action", "").upper()
    if action != "OPEN":
        return  # Skip CLOSE
    
    sym = signal_data.get("symbol", "?").replace("_", "")
    typ = signal_data.get("type", "").upper()
    price = float(signal_data.get("price", 0))
    digits = int(signal_data.get("digits", 2))
    
    emoji = "🎯" if typ == "BUY" else ("🎱" if typ == "SELL" else "⚪️")
    
    # Bulatkan harga (round half up)
    if digits == 2:
        harga_bulat = str(int(round(price)))
    else:
        harga_bulat = f"{round(price, digits):.{digits}f}"
    
    now_wib = datetime.now(timezone.utc).astimezone(tz=timezone(timedelta(hours=7))).strftime("%H:%M WIB")
    message = f"{emoji} <b>{typ} NOW</b> {sym} <b>{harga_bulat}</b>\n{now_wib}"
    
    try:
        await client.send_message(TG_CHAT_ID, message)
        log(f"✅ SENT: {message[:100]}")
        return True
    except Exception as e:
        log(f"❌ SEND FAILED: {e}")
        return False

def round_price(price, digits):
    """Bulatkan harga."""
    try:
        val = float(price)
        if digits == 2:
            return str(int(round(val)))
        return f"{round(val, digits):.{digits}f}"
    except:
        return str(price)

async def main():
    log(f"Loading session from {SESSION_FILE}")
    
    # Buat client dengan session file
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    
    async with client:
        user = await client.get_me()
        log(f"✅ Logged in as {user.first_name} ({user.id})")
        
        # Loop: cek queue JSON dari receiver, kirim sinyal
        while True:
            import json
            
            # Baca queue file dari receiver Python
            queue_path = "/root/mt5-signal/queue.json"
            try:
                with open(queue_path) as f:
                    queue = json.load(f)
            except:
                await asyncio.sleep(5)
                continue
            
            if not queue:
                await asyncio.sleep(5)
                continue
            
            # Ambil pesan pertama dari queue
            msg = queue[0]
            
            # Parse format simple: "🎯 BUY NOW XAUUSD 4820\nHH:mm WIB"
            lines = msg.strip().split('\n')
            if len(lines) < 2:
                log(f"⚠️ Invalid format: {msg[:50]}")
                queue.pop(0)
                continue
            
            text_line = lines[0]
            time_line = lines[1]
            
            # Extract emoji, type, pair, price
            import re
            match = re.search(r'(🎯|🎱)(?:\s+)?(?:<b>)?([A-Z]+)\s+NOW\s+([A-Z0-9]+)<(/b)?\s+([0-9.]+)', text_line)
            if match:
                emoji_char, typ, sym, _, harga = match.groups()
                
                signal = {
                    "action": "OPEN",
                    "type": typ,
                    "symbol": sym,
                    "price": float(harga),
                    "digits": 2 if "XAU" in sym else max(len(harga.split('.')[-1]) if '.' in harga else 2, 2)
                }
                
                # Kirim sinyal via selfbot
                ok = await send_signal(client, signal)
                
                if ok:
                    queue.pop(0)
                    try:
                        with open(queue_path, 'w') as qf:
                            json.dump(queue, qf)
                    except:
                        pass
            else:
                log(f"⚠️ Cannot parse: {text_line[:100]}")
                queue.pop(0)
                continue
            
            await asyncio.sleep(1)

if __name__ == "__main__":
    if API_ID == 0 or not API_HASH:
        log("❌ Error: API_ID dan API_HASH wajib diisi!")
        log("Environment variables needed:")
        log("  TG_API_ID=xxxxx")
        log("  TG_API_HASH=xxxxxxxxxxx")
        log("  TG_PHONE_NUMBER=+628xxxxx")
        sys.exit(1)
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        log("👋 Shutting down...")
