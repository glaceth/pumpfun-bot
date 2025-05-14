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

# Envoyer une alerte Telegram
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print("❌ Erreur Telegram:", e)

# Lire la mémoire
def load_memory(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

# Sauver la mémoire
def save_memory(data, file):
    with open(file, "w") as f:
        json.dump(data, f)

# Vérifier si un token est déjà vu
def is_new_token(token_address, memory):
    return token_address not in memory

# Analyser les tokens
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
        mc = float(token.get("fullyDilutedValuation", 0))
        lq = float(token.get("liquidity", 0))
        mentions = token.get("mentions", 0)
        rugscore = token.get("rugscore", 0)
        age = float(token.get("age", 0))
        holders = token.get("holders", 0)

        # Filtres principaux (souples)
        if mc < 30000:
            print(f"⛔ {name} filtré (MC={mc}, LQ={lq}, Mentions={mentions}, Rugscore={rugscore}, Age={age}h)")
            memory[token_address] = now
            continue

        # Alerte
        print(f"✅ {name} PASSE ! MC={mc} LQ={lq} Holders={holders} Mentions={mentions} Rugscore={rugscore} Age={age}")
        msg = f"🔥 {name} (${symbol})\nMC: {int(mc)}\nLQ: {int(lq)}\nMentions: {mentions}\nRugscore: {rugscore}\nhttps://pump.fun/{token_address}"
        send_telegram_message(msg)
        memory[token_address] = now

    save_memory(memory, MEMORY_FILE)

# Lancer le serveur Flask
def run_flask():
    app.run(host="0.0.0.0", port=8080)

# Boucle principale
def start_loop():
    while True:
        check_tokens()
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    start_loop()
