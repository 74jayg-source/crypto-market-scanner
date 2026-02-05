import os
import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

text = "✅ Jays Chart Scanner is online (test message)"
url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

r = requests.post(url, data={"chat_id": CHAT_ID, "text": text}, timeout=20)
print("Status:", r.status_code)
print("Response:", r.text)
