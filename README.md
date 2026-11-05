# Telegram FlowFame Automation

This repository automatically claims FlowFame members for a Telegram channel, rotating the channel's username every hour to generate a fresh link.

## 🛠️ Setup Instructions

### 1. Generate Telegram Session String
You need a session string to log in without entering a code every hour.
Run this script **on your local computer** (not in GitHub Actions):
```python
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = 123456  # Replace with your API ID
API_HASH = "your_api_hash"  # Replace with your API Hash

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\nYOUR SESSION STRING:\n", client.session.save())
    input("Press Enter to close...")
