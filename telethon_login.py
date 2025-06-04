from telethon.sync import TelegramClient
from config import API_ID, API_HASH


with TelegramClient('autoposter_session', API_ID, API_HASH) as client:
    client.start()  
    print("Authorization complete!")