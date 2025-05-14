import os
import json
import requests
import time
from flask import Flask
from threading import Thread

# Flask setup
app = Flask(__name__)

@app.route('/')
def home():
    return "Pump.fun ULTIMATE bot is running."

def run_flask():
    app.run(host='0.0.0.0', port=8080)

flask_thread = Thread(target=run_flask)
flask_thread.start()

# Lire clés depuis Render
with open("/etc/secrets/MORALIS_API") as f:
    API_KEY = f.read().strip()

with open("/etc/secrets/TELEGRAM_TOKEN") as f:
    TELEGRAM_TOKEN = f.read().strip()

with open("/etc/secrets/CHAT_ID") as f:
    CHAT_ID = f.read().strip()

# Fichier mémoire
MEMORY_FILE = "token_memory_ultimate.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f)

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": message}
    try:
        r = requests.post(url, json=data)
        if r.status_code != 200:
            print("❌ Erreur envoi Telegram :", r.text)
    except Exception as e:
        print("❌ Exception Telegram :", e)

def fetch_graduated_tokens():
    url = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/graduated?limit=100"
    headers = {
        "accept": "application/json",
        "X-API-Key": API_KEY
    }
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            return r.json()["result"]
        else:
            print("❌ Erreur API Moralis :", r.text)
            return []
    except Exception as e:
        print("❌ Exception API Moralis :", e)
        return []

def is_promising(token):
    try:
        liquidity = float(token.get("liquidity", 0))
        marketcap = float(token.get("fullyDilutedValuation", 0))
        name = token.get("name") or "Unnamed"

        if marketcap < 60000 and liquidity > 30000:
            print(f"✅ {name} passe les filtres (MC={marketcap}, LQ={liquidity})")
            return True
        else:
            print(f"⛔️ {name} filtré (MC={marketcap}, LQ={liquidity})")
            return False
    except Exception as e:
        print("Erreur filtre :", e)
        return False

def main_loop():
    memory = load_memory()

    while True:
        tokens = fetch_graduated_tokens()
        new_detected = []

        for token in tokens:
            addr = token["tokenAddress"]
            if addr not in memory and is_promising(token):
                message = f"""
🚀 Nouveau token prometteur détecté :

Name: {token.get('name')}
Liquidity: {token.get('liquidity')}
Market Cap: {token.get('fullyDilutedValuation')}
Price (USD): {token.get('priceUsd')}
"""
                send_telegram(message)
                memory[addr] = True
                new_detected.append(token.get("name"))

        if new_detected:
            print(f"📦 {len(new_detected)} tokens envoyés sur Telegram.")

        save_memory(memory)
        time.sleep(60)

# Démarrer la boucle
main_loop()
