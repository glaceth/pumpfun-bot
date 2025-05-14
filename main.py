import requests
import time
import json
import os
from datetime import datetime
from threading import Thread
from flask import Flask

# Flask keep-alive pour Render
app = Flask(__name__)
@app.route('/')
def home():
    return "Pump.fun ULTIMATE bot is running."

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# Configuration & secrets
API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."  # remplace si nécessaire
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = "7604145219"
MEMORY_FILE = "token_memory_ultimate.json"
LOG_FILE = "token_daily_log.json"
BONDED_FILE = "token_bonded_list.json"

# Seuils
MARKETCAP_THRESHOLD = 60000
PROMETTEUR_THRESHOLD = 70000
STEP_ALERT = 10000
TOP10_ALERT_THRESHOLD = 85

# Moralis API
BASE_URL = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun"
HEADERS = {
    "accept": "application/json",
    "X-API-Key": API_KEY
}

# Journal du jour
daily_log = {"scanned": [], "alerted": [], "near_threshold": []}

# Alertes Telegram
def send_telegram_alert(token, market_cap, extra_info=""):
    name = token.get("name") or "N/A"
    symbol = token.get("symbol") or "N/A"
    mint = token.get("tokenAddress")
    price = token.get("priceUsd")
    liquidity = token.get("liquidity")
    link = f"https://pump.fun/{mint}"

    message = (
        f"🚨 Token Pump Alert 🚨\n"
        f"Name: {name}\n"
        f"Symbol: {symbol}\n"
        f"Market Cap: ${round(market_cap):,}\n"
        f"Price: ${price}\n"
        f"Liquidity: {liquidity}\n"
        f"{extra_info}\n"
        f"🔗 {link}"
    )

    if market_cap >= PROMETTEUR_THRESHOLD:
        message += "\n🔥 Prometteur !"

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message
    }
    requests.post(url, data=data)

# Récapitulatif journalier
def send_daily_log():
    if not daily_log["scanned"]:
        return

    message = f"📊 Pump.fun Summary – {datetime.now().strftime('%d %b %Y %H:%M')}\n"
    message += f"Tokens scanned: {len(daily_log['scanned'])}\n"
    message += f"Alerts sent: {len(daily_log['alerted'])}\n"

    if daily_log['alerted']:
        message += "\n🟢 Alerted tokens:\n" + "\n".join(daily_log['alerted'])

    if daily_log['near_threshold']:
        message += "\n⚪ Near threshold (50k–59k):\n" + "\n".join(daily_log['near_threshold'])

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message
    }
    requests.post(url, data=data)

# Charger la mémoire
def load_memory():
    try:
        with open(MEMORY_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_memory(memory):
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f)

# Détails du token
def get_token_details(mint):
    stats = {}
    try:
        vol = requests.get(f"{BASE_URL}/volume?tokenAddress={mint}", headers=HEADERS).json()
        stats["volume1h"] = vol.get("volume1hQuote", 0)
        stats["volume24h"] = vol.get("volume24hQuote", 0)

        holders = requests.get(f"{BASE_URL}/holders?tokenAddress={mint}", headers=HEADERS).json()
        top10 = holders.get("topHolders", [])[:10]
        stats["top10pct"] = sum(h.get("percentage", 0) for h in top10)

        snipers = requests.get(f"{BASE_URL}/snipers?tokenAddress={mint}", headers=HEADERS).json()
        stats["sniper_count"] = len(snipers.get("result", []))

        swaps = requests.get(f"{BASE_URL}/swaps?tokenAddress={mint}", headers=HEADERS).json()
        buy_amount = 0
        for tx in swaps.get("result", []):
            if tx.get("side") == "buy":
                buy_amount += tx.get("quoteAmount", 0)
        stats["buy_total"] = buy_amount

    except Exception as e:
        print(f"[{mint}] Erreur stats avancées : {e}")

    return stats

# Scan complet
def check_tokens():
    memory = load_memory()
    response = requests.get(f"{BASE_URL}/graduated", headers=HEADERS, params={"limit": 100})
    if response.status_code != 200:
        print("Erreur API")
        return

    tokens = response.json().get("result", [])
    for token in tokens:
        try:
            mint = token["tokenAddress"]
            price = float(token.get("priceUsd") or 0)
            liquidity = float(token.get("liquidity") or 0)
            market_cap = price * liquidity
            symbol = token.get("symbol", mint[:4])

            daily_log["scanned"].append(symbol)

            if 50000 <= market_cap < MARKETCAP_THRESHOLD:
                daily_log["near_threshold"].append(f"{symbol} (${round(market_cap):,})")

            if market_cap < MARKETCAP_THRESHOLD:
                continue

            prev = memory.get(mint, 0)
            if mint not in memory or (market_cap - prev) >= STEP_ALERT:
                stats = get_token_details(mint)
                extra = (
                    f"👥 Top 10 Holders: {round(stats['top10pct'], 1)}%" +
                    (" ⚠️ Trop centralisé !" if stats['top10pct'] > TOP10_ALERT_THRESHOLD else "") +
                    f"\n📊 Volume: 1h ${int(stats['volume1h'])} | 24h ${int(stats['volume24h'])}" +
                    f"\n🐳 Whale buys: ${int(stats['buy_total'])}" +
                    f"\n🧠 Snipers: {stats['sniper_count']}"
                )
                send_telegram_alert(token, market_cap, extra_info=extra)
                memory[mint] = market_cap
                daily_log["alerted"].append(f"{symbol} (${round(market_cap):,})")
        except Exception as e:
            print("Erreur scan token :", e)

    save_memory(memory)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Scan terminé")

# Tokens fraîchement gradués détectés par bonding_tracker
def check_new_graduated_tokens():
    if not os.path.exists(BONDED_FILE):
        return []

    try:
        with open(BONDED_FILE, "r") as f:
            memory = json.load(f)
    except:
        return []

    new_tokens = list(memory.keys())
    with open(BONDED_FILE, "w") as f:
        json.dump({}, f)

    return new_tokens

# === Lancement et boucle principale ===
flask_thread = Thread(target=run_flask)
flask_thread.start()

while True:
    # 🔄 Scanner les tokens fraîchement gradués détectés par bonding_tracker.py
    new_graduated = check_new_graduated_tokens()
    if new_graduated:
        print(f"[🚀] {len(new_graduated)} token(s) fraîchement gradués à scanner en priorité !")

    check_tokens()

    now = datetime.now()
    if now.hour in [6, 20] and now.minute == 0:
        send_daily_log()
        daily_log = {"scanned": [], "alerted": [], "near_threshold": []}

    time.sleep(60)

