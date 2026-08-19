#!/usr/bin/env python3
"""
MT5 Signal Selfbot Setup — Interactive login with OTP/2FA support
Run this once to authenticate and save session.
"""

import sys
import os
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

SESSION_FILE = "/root/mt5-signal/6285196827787.session"

print("=" * 60)
print("MT5 SIGNAL SELFBOT SETUP")
print("=" * 60)
print("\nLangkah-langkah:")
print("1. Buka https://my.telegram.org → Login dengan nomor HP Anda")
print("2. Klik 'API development tools' di menu kiri")
print("3. Buat app baru (atau pakai yang ada)")
print("4. Copy API_ID (angka) dan API_HASH (string hex)")
print("5. Masukkan nilai tersebut di bawah ini\n")

api_id_input = input("Masukkan API_ID dari my.telegram.org: ").strip()
api_hash = input("Masukkan API_HASH dari my.telegram.org: ").strip()

if not api_id_input or not api_hash:
    print("\n❌ Error: API_ID dan API_HASH WAJIB diisi!")
    print("   Silakan daftar di https://my.telegram.org dulu.")
    sys.exit(1)

try:
    api_id = int(api_id_input)
except ValueError:
    print("\n❌ Error: API_ID harus berupa angka!")
    sys.exit(1)

phone = input("Masukkan nomor HP (+628xxxxx): ").strip()
if not phone.startswith('+'):
    phone = '+' + phone

print(f"\n📱 Session akan disimpan ke: {SESSION_FILE}")
print(f"🔐 Menggunakan nomor: {phone}")
print("\n✅ Klik OK untuk lanjut login...")

# Buat client dan mulai proses login
client = TelegramClient(SESSION_FILE, api_id, api_hash)

async def login():
    # Cek apakah session sudah ada
    if os.path.exists(SESSION_FILE):
        print("\n⚠️ Session existing found. Reusing...")
    else:
        print("\n🆕 New session - will prompt for OTP")
    
    async with client:
        # Check if logged in
        try:
            me = await client.get_me()
            print(f"\n✅ Already logged in as: @{me.username or me.first_name}")
            return True
        except:
            pass
        
        # Send code to trigger OTP
        print("\n📨 Sending code to your phone...")
        code = await client.send_code_request(phone)
        
        # Prompt for OTP
        otp_input = input("Masukkan kode OTP yang dikirim ke WhatsApp/SMS: ").strip()
        
        # Sign in
        print("\n🔑 Signing in...")
        try:
            result = await client.sign_in(phone, otp_input, password=None)
            if result.success:
                print(f"\n✅ SUCCESS! Logged in successfully.")
                
                me = await client.get_me()
                print(f"\n👤 Account: @{me.username or me.first_name} ({me.id})")
                print(f"💾 Session saved to: {SESSION_FILE}")
                return True
        except SessionPasswordNeededError:
            print("\n⚠️ Your account has 2FA enabled.")
            two_fa_password = input("Enter 2FA password: ").strip()
            try:
                result = await client.sign_in(phone, None, password=two_fa_password)
                if result.success:
                    print(f"\n✅ SUCCESS! Logged in with 2FA.")
                    me = await client.get_me()
                    print(f"\n👤 Account: @{me.username or me.first_name} ({me.id})")
                    print(f"💾 Session saved to: {SESSION_FILE}")
                    return True
            except Exception as e:
                print(f"\n❌ Error during 2FA login: {e}")
                return False
        except Exception as e:
            print(f"\n❌ Login failed: {e}")
            print("\nTips: Pastikan API_ID/API_HASH benar & nomor HP format internasional (+62xxx)")
            return False
    
    return False

def main():
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    success = loop.run_until_complete(login())
    loop.close()
    
    if success:
        print("\n🎉 SETUP COMPLETE!")
        print("\nNext steps:")
        print("1. Run the selfbot: python3 selfbot.py")
        print("2. The bot will read queue.json and send signals automatically")
        sys.exit(0)
    else:
        print("\n❌ SETUP FAILED")
        print("Please check your API_ID, API_HASH, and OTP code.")
        sys.exit(1)

if __name__ == "__main__":
    main()
