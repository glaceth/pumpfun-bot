import os
import json
import time
import requests
from datetime import datetime
from flask import Flask
from threading import Thread

# === Config & Secrets depuis Render ===
with open("/etc/secrets/MORALIS_API") as f:
    API_KEY = f.read().strip()

with open("/etc/secrets/TELEGRAM_TOKEN") as f:
    TELEGRAM_TOKEN = f.read().strip()

with open("/etc/secrets/CHAT_ID") as f:
    CHAT_ID = f.read().strip()

# === Fichiers ===
MEMORY_FILE = "token_memory_ultimate.json"
BONDED_FILE = "token_bonded_list.json"
LOG_FILE = "token_daily_log.json"

# === Initialisation mémoire ===
if not os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "w") as f:
        json.dump({}, f)

if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w") as f:
        json.dump({"scanned": [], "alerted": [], "near_threshold": []}, f)

# === Flask ===
app = Flask(__name__)

@app.route("/")
def index():
    return "Bot actif"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# === Telegram ===
def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Erreur Telegram : {e}")

# === Récupérer les tokens gradués ===
def fetch_graduated_tokens():
    url = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/graduated?limit=100"
    headers = {"X-API-Key": API_KEY, "Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers)
        return response.json().get("result", [])
    except Exception as e:
        print("Erreur API graduated:", e)
        return []

# === Analyse de tokens ===
def check_tokens():
    tokens = fetch_graduated_tokens()
    now = datetime.utcnow()

    with open(MEMORY_FILE, "r") as f:
        memory = json.load(f)

    with open(LOG_FILE, "r") as f:
        daily_log = json.load(f)

    for token in tokens:
        address = token.get("tokenAddress")
        if not address or address in memory:
            continue

        market_cap = float(token.get("fullyDilutedValuation", 0))
        liquidity = float(token.get("liquidity", 0))
        mentions = token.get("mentions", 0)
        volume = float(token.get("volume", 0))
        holders = int(token.get("holders", 0))
        rugscore = token.get("rugscore", 0)
        created_at = token.get("createdAt", now.isoformat())

        try:
            pair_age = (now - datetime.fromisoformat(created_at.replace("Z", ""))).total_seconds() / 3600
        except:
            pair_age = 0

        # === Filtres ===
        if market_cap < 60000 or liquidity < 5000 or mentions < 25 or rugscore < 70:
            print(f"⛔ Token filtré : {token.get('name', 'N/A')} "
                  f"(MC={market_cap}, LQ={liquidity}, Vol={volume}, Holders={holders}, "
                  f"Rugscore={rugscore}, Mentions={mentions}, Age={round(pair_age, 2)}h)")
            memory[address] = True
            continue

        # === Envoi Telegram ===
        msg = f"🔥 {token.get('name')} détecté !\nMC: {market_cap}$\nLQ: {liquidity}$\nMentions: {mentions}"
        send_telegram_message(msg)
        print(f"✅ {token.get('name')} envoyé sur Telegram !")

        # === Mémorisation ===
        memory[address] = True
        daily_log["scanned"].append(address)
        daily_log["alerted"].append(address)

    # === Sauvegarde mémoire ===
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f)

    with open(LOG_FILE, "w") as f:
        json.dump(daily_log, f)

# === Tâche journalière ===
def send_daily_log():
    with open(LOG_FILE, "r") as f:
        log = json.load(f)
    scanned = len(log["scanned"])
    alerted = len(log["alerted"])
    msg = f"📊 Résumé du jour :\nScannés : {scanned}\nAlertés : {alerted}"
    send_telegram_message(msg)

# === Lancer le bot ===
flask_thread = Thread(target=run_flask)
flask_thread.start()

while True:
    now = datetime.utcnow()
    if now.hour in [6, 20] and now.minute == 0:
        send_daily_log()
    check_tokens()
    time.sleep(60)
