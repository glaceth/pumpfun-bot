
import os
import time
import json
import requests
from datetime import datetime
from flask import Flask, request
from threading import Thread

# Chargement sécurisé des secrets
with open("/etc/secrets/TELEGRAM_TOKEN") as f:
    TELEGRAM_TOKEN = f.read().strip()
with open("/etc/secrets/CHAT_ID") as f:
    CHAT_ID = f.read().strip()
with open("/etc/secrets/ADMIN_USER_ID") as f:
    ADMIN_USER_ID = f.read().strip()
with open("/etc/secrets/MORALIS_API") as f:
    MORALIS_API = f.read().strip()
with open("/etc/secrets/HELIUS_API") as f:
    HELIUS_API = f.read().strip()
with open("/etc/secrets/CALLSTATIC_API") as f:
    CALLSTATIC_API = f.read().strip()
with open("/etc/secrets/OPENAI_API_KEY") as f:
    OPENAI_API_KEY = f.read().strip()

# Initialisation Flask
app = Flask(__name__)

@app.route("/")
def home():
    return "Pump.fun Bot is live!"

@app.route(f"/bot/{TELEGRAM_TOKEN}", methods=["POST"])
def bot_webhook():
    data = request.get_json()
    print("✅ /bot route registered")
    return "OK"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

def fake_loop():
    while True:
        print("Loop started. (fake loop for example)")
        time.sleep(30)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    fake_loop()
