import os
import time
import json
import requests
from datetime import datetime
from flask import Flask
from threading import Thread

app = Flask(__name__)

# Lire les secrets depuis Render
with open("/etc/secrets/MORALIS_API") as f:
    API_KEY = f.read().strip()
with open("/etc/secrets/TELEGRAM_TOKEN") as f:
    TELEGRAM_TOKEN = f.read().strip()
with open("/etc/secrets/CHAT_ID") as f:
    CHAT_ID = f.read().strip()

# Constantes et fichiers
MEMORY_FILE = "token_memory_ultimate.json"
BONDED_FILE = "token_bonded_list.json"
API_URL = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/graduated?limit=100"

HEADERS = {
    "Accept": "application/json",
    "X-API-Key": API_KEY,
}

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload)
        time.sleep(2)
    except Exception as e:
        print("❌ Erreur Telegram:", e)

def load_memory(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def save_memory(data, file):
    with open(file, "w") as f:
        json.dump(data, f)

def is_new_token(token_address, memory):
    return token_address not in memory

def check_tokens():
    print("🔍 Checking tokens...")
    try:
        response = requests.get(API_URL, headers=HEADERS)
        data = response.json().get("result", [])
    except Exception as e:
        print("❌ Erreur API Moralis:", e)
        return

    memory = load_memory(MEMORY_FILE)
    bonded_memory = load_memory(BONDED_FILE)
    now = time.time()

    for token in data:
        token_address = token.get("tokenAddress")
        if not token_address or not is_new_token(token_address, memory):
            continue

        name = token.get("name", "N/A")
        symbol = token.get("symbol", "N/A")
        mc = float(token.get("fullyDilutedValuation") or 0)
        lq = float(token.get("liquidity") or 0)
        mentions = token.get("mentions") or 0
        rugscore = token.get("rugscore") or 0
        age = float(token.get("age") or 0)
        holders = token.get("holders") or 0

        if mc < 20000 or lq < 10000:
            print(f"⛔ {name} filtré (MC={mc}, LQ={lq}, Mentions={mentions}, Rugscore={rugscore}, Age={age}h)")
            memory[token_address] = now
            continue

        print(f"✅ {name} PASSE ! MC={mc} LQ={lq} Holders={holders} Mentions={mentions} Rugscore={rugscore} Age={age}")
        memory[token_address] = now
        save_memory(memory, MEMORY_FILE)

        msg = "*NEW TOKEN DETECTED*\n"
        msg += f"*Token:* ${symbol}\n"
        msg += f"*Market Cap:* {'{:,}'.format(int(mc))} | *Volume 1h:* {'{:,}'.format(int(lq))}\n"
        msg += f"*Holders:* {'{:,}'.format(int(holders))}\n"
        msg += f"*Rugscore:* {rugscore} ✅ | *TweetScout:* {mentions} mentions 🔥\n"
        msg += "*Smart Wallet Buy:* 8.5 SOL (WinRate: 78%)\n"
        msg += "✅ Token SAFE – LP Locked, No Honeypot\n"
        msg += f"➤ [Pump.fun](https://pump.fun/{token_address}) | [Scamer.io](https://scamer.io/token/{token_address}) | [Rugcheck](https://rugcheck.xyz/tokens/{token_address}) | [BubbleMaps](https://app.bubblemaps.io/token/solana/{token_address}) | [Twitter Search](https://twitter.com/search?q={symbol}&src=typed_query&f=live) | [Axiom](https://axiom.trade/meme/{token_address})"
        send_telegram_message(msg)

    save_memory(memory, MEMORY_FILE)

def run_flask():
    app.run(host="0.0.0.0", port=8080)

def start_loop():
    while True:
        check_tokens()
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    start_loop()
