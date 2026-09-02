#!/usr/bin/env python3
"""
MT5 Signal Selfbot LOGIN (multi akun) — jalankan via SSH terminal (butuh input OTP).

Usage:
  python3 login.py                          # lihat daftar akun di config + status
  python3 login.py <nama-akun>              # login akun sesuai telegram_config.json
  python3 login.py <nama> <phone> <sess>    # login akun baru & simpan ke config

Nomor HP format internasional, contoh: +6281234567890
"""
import asyncio
import json
import os
import re
import sys

from telethon import TelegramClient

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(BASE, "telegram_config.json")
LEGACY_SESSION = os.path.join(BASE, "6285196827787")
LEGACY_API_ID = 38274094
LEGACY_API_HASH = "c57671be8ccbd29f37dd82c97a28370e"


def load_cfg():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"accounts": [], "routes": []}


def save_cfg(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG)


def sess_path(sess):
    return sess if os.path.isabs(sess) else os.path.join(BASE, sess)


async def do_login(name, phone, session, api_id, api_hash):
    client = TelegramClient(sess_path(session), api_id, api_hash)
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"✅ '{name}' sudah login sebagai: {me.first_name} (@{me.username or 'no username'})")
        await client.disconnect()
        return True

    print(f"📨 Mengirim kode ke {phone}...")
    sent = await client.send_code_request(phone)
    print("✅ Kode dikirim. Cek Telegram/SMS di nomor lo.")
    code = input("Masukkan kode OTP: ").strip()
    try:
        await client.sign_in(phone, code, phone_code_hash=sent.phone_code_hash)
        me = await client.get_me()
        print(f"\n✅ BERHASIL LOGIN! {me.first_name} (ID: {me.id})")
        print(f"💾 Session disimpan: {sess_path(session)}.session")
        await client.disconnect()
        return True
    except Exception as e:
        msg = str(e)
        if "PASSWORD" in msg.upper() or "2fa" in msg.lower():
            pwd = input("Akun ini pakai 2FA. Masukkan password Telegram: ").strip()
            try:
                await client.sign_in(password=pwd)
                me = await client.get_me()
                print(f"\n✅ BERHASIL LOGIN (2FA)! {me.first_name} (ID: {me.id})")
                await client.disconnect()
                return True
            except Exception as e2:
                print(f"❌ Gagal login 2FA: {e2}")
        else:
            print(f"❌ Gagal login: {e}")
        await client.disconnect()
        return False


async def show_status():
    cfg = load_cfg()
    accs = cfg.get("accounts", [])
    if not accs:
        print("Config kosong — cuma akun legacy 6285196827787.")
        accs = [{"name": "legacy", "session": "6285196827787",
                 "api_id": LEGACY_API_ID, "api_hash": LEGACY_API_HASH}]
    print("=" * 50)
    for a in accs:
        session = a.get("session") or f"tg_{re.sub(r'[^a-zA-Z0-9_-]+', '_', a.get('name', 'akun'))}"
        path = sess_path(session) + ".session"
        ada = "✔ ada" if os.path.exists(path) else "✘ belum ada session"
        client = TelegramClient(sess_path(session), int(a.get("api_id") or LEGACY_API_ID),
                                str(a.get("api_hash") or LEGACY_API_HASH))
        await client.connect()
        auth = await client.is_user_authorized()
        await client.disconnect()
        status = "🟢 authorized" if auth else "🔴 belum login"
        print(f"  {a.get('name', '?'):20} {status:15} {ada}")


async def main():
    args = sys.argv[1:]
    if not args:
        await show_status()
        print("\nLogin akun: python3 login.py <nama-akun>")
        print("Akun baru : python3 login.py <nama> <+62xxx> [<nama-file-session>]")
        return

    name = args[0]
    cfg = load_cfg()
    acc = next((a for a in cfg.get("accounts", []) if a.get("name") == name), None)

    if len(args) >= 3:
        phone = args[1]
        session = args[2] if len(args) > 2 else f"tg_{re.sub(r'[^a-zA-Z0-9_-]+', '_', name)}"
        api_id = int(input(f"API_ID [{LEGACY_API_ID}]: ").strip() or LEGACY_API_ID)
        api_hash = input(f"API_HASH [{LEGACY_API_HASH[:6]}...]: ").strip() or LEGACY_API_HASH
        ok = await do_login(name, phone, session, api_id, api_hash)
        if ok:
            if acc:
                acc.update({"session": session, "api_id": api_id, "api_hash": api_hash, "enabled": True})
            else:
                cfg.setdefault("accounts", []).append({
                    "name": name, "session": session,
                    "api_id": api_id, "api_hash": api_hash,
                    "enabled": True, "default": not cfg.get("accounts"),
                })
            save_cfg(cfg)
            print(f"💾 '{name}' tersimpan di telegram_config.json — selfbot hot-reload dalam ≤5s")
        sys.exit(0 if ok else 1)

    if not acc:
        print(f"❌ Akun '{name}' gak ada di telegram_config.json.")
        print(f"   Buat baru: python3 login.py {name} +628xxx")
        sys.exit(1)
    ok = await do_login(name, acc.get("phone") or input("Nomor HP (+62xxx): ").strip(),
                        acc.get("session") or f"tg_{name}",
                        int(acc.get("api_id") or LEGACY_API_ID),
                        str(acc.get("api_hash") or LEGACY_API_HASH))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
