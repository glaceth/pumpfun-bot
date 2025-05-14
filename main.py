import requests
import time
import json
import os
from datetime import datetime
from threading import Thread
from flask import Flask

# === Flask keep-alive pour Render ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Pump.fun ULTIMATE bot is running."

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# === Config & Env ===
# Lire l'API key depuis le fichier secret sur Render
with open("/etc/secrets/MORALIS_API") as f:
    API_KEY = f.read().strip()

with open("/etc/secrets/TELEGRAM_TOKEN") as f:
    TELEGRAM_TOKEN = f.read().strip()

with open("/etc/secrets/CHAT_ID") as f:
    CHAT_ID = f.read().strip()


MEMORY_FILE = "token_memory_ultimate.json"
LOG_FILE = "token_daily_log.json"
BONDED_FILE = "token_bonded_list.json"

BASE_URL = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/graduated"
HEADERS = {
    "accept": "application/json",
    "X-API-Key": API_KEY
}

# === Envoie Telegram ===
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=data)
    except Exception as e:
        print("❌ Erreur Telegram:", e)

# === Mémoire locale ===
def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    return {}

def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

# === Chargement des tokens déjà alertés ===
def check_new_graduated_tokens():
    file_path = BONDED_FILE
    if not os.path.exists(file_path):
        return []
    try:
        with open(file_path, "r") as f:
            memory = json.load(f)
    except:
        return []
    new_tokens = list(memory.keys())
    with open(file_path, "w") as f:
        json.dump({}, f)
    return new_tokens

# === Log quotidien ===
def send_daily_log():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = f"📋 *Daily Log {now}*\nAucun token détecté aujourd'hui."
    send_telegram(msg)

# === Scan des tokens ===
def check_tokens():
    try:
        response = requests.get(BASE_URL, headers=HEADERS)
        data = response.json()

        if "result" not in data:
            print("❌ Erreur API: pas de 'result'")
            return

        memory = load_memory()
        new_alerts = 0

        for token in data["result"]:
            token_address = token.get("tokenAddress")
            if token_address in memory:
                continue

            name = token.get("name") or "Unknown"
            symbol = token.get("symbol") or ""
            liquidity = float(token.get("liquidity") or 0)
            market_cap = float(token.get("fullyDilutedValuation") or 0)
            bonding_curve_progress = float(token.get("bondingCurveProgress") or 0)

            # Log technique pour suivi
            print(f"🔍 {name} | MC: {market_cap} | LQ: {liquidity} | Curve: {bonding_curve_progress:.2f}%")

            # Filtres plus permissifs
            if liquidity > 10000 and market_cap > 20000 and bonding_curve_progress >= 92:
                msg = (
                    f"🚀 *{name}* ({symbol})\n"
                    f"💧 Liquidity: {int(liquidity)}\n"
                    f"📈 Market Cap: {int(market_cap)}\n"
                    f"📊 Curve Progress: {bonding_curve_progress:.2f}%\n"
                    f"🔗 Explorer: https://pump.fun/{token_address}"
                )
                send_telegram(msg)
                memory[token_address] = True
                new_alerts += 1

        if new_alerts > 0:
            print(f"✅ {new_alerts} token(s) envoyés sur Telegram.")
        save_memory(memory)

    except Exception as e:
        print("❌ Erreur dans check_tokens():", e)

# === Lancement principal ===
if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.start()

    while True:
        try:
            new_graduated = check_new_graduated_tokens()
            if new_graduated:
                print(f"🧪 {len(new_graduated)} tokens récemment gradués à vérifier en priorité.")
            check_tokens()

            # Envoi log à 6h du matin
            now = datetime.now()
            if now.hour == 6 and now.minute == 0:
                send_daily_log()

        except Exception as e:
            print("❌ Erreur boucle principale:", e)

        time.sleep(60)
