#!/usr/bin/env python3
"""
MT5 Signal Selfbot LOGIN — Jalankan via SSH terminal (butuh input OTP)
Usage: python3 login.py
"""
import asyncio, os, sys
from telethon import TelegramClient

API_ID = 38274094
API_HASH = "c57671be8ccbd29f37dd82c97a28370e"
PHONE = "+6285196827787"
SESSION = "/root/mt5-signal/6285196827787.session"

print("=" * 50)
print("MT5 SIGNAL SELFBOT LOGIN")
print("=" * 50)

async def main():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()

    # Cek kalau sudah login
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"✅ Sudah login sebagai: {me.first_name} (@{me.username or 'no username'})")
        await client.disconnect()
        return

    # Kirim kode OTP
    print(f"📨 Mengirim kode ke {PHONE}...")
    sent = await client.send_code_request(PHONE)
    print(f"✅ Kode dikirim. Cek Telegram/SMS di nomor lo.")

    code = input("Masukkan kode OTP: ").strip()

    try:
        await client.sign_in(PHONE, code, phone_code_hash=sent.phone_code_hash)
        me = await client.get_me()
        print(f"\n✅ BERHASIL LOGIN! Account: {me.first_name} (ID: {me.id})")
        print(f"💾 Session disimpan: {SESSION}")
    except Exception as e:
        print(f"❌ Gagal login: {e}")
        await client.disconnect()
        sys.exit(1)

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
