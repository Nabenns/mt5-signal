"""Test kirim custom emoji (ijo muter) + format persis message #15"""
import asyncio, random
from telethon import TelegramClient
from telethon.tl.functions.messages import SendMessageRequest
from telethon.tl.types import MessageEntityCustomEmoji, MessageEntityItalic

SESSION = "/root/mt5-signal/6285196827787"
API_ID = 38274094
API_HASH = "c57671be8ccbd29f37dd82c97a28370e"
CHANNEL = -1004479253024
EMOJI_ID = 5296596700704548349  # custom emoji ijo muter dari message #15

async def test():
    client = TelegramClient(SESSION, API_ID, API_HASH)
    await client.connect()
    if not await client.is_user_authorized():
        print("NOT AUTHORIZED")
        return

    entity = await client.get_entity(CHANNEL)

    # Format persis message #15: emoji + nbsp + "BUY NOW XAUUSD " + harga italic
    prefix = "\U0001F4B0\u00a0BUY NOW XAUUSD "
    harga = "4821"
    text = prefix + harga
    # offset UTF-16: 💰 = 2 unit, \xa0 = 1, "BUY NOW XAUUSD " = 15 → harga di offset 18
    entities = [
        MessageEntityCustomEmoji(offset=0, length=2, document_id=EMOJI_ID),
        MessageEntityItalic(offset=18, length=len(harga)),
    ]

    await client(SendMessageRequest(
        peer=entity,
        message=text,
        entities=entities,
        random_id=random.randrange(-2**63, 2**63),
    ))
    print("✅ SENT dengan custom emoji!")
    await client.disconnect()

asyncio.run(test())
