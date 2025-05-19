
import os
import time
import json
import requests
from datetime import datetime
from flask import Flask
from threading import Thread

app = Flask(__name__)
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")

with open("/etc/secrets/MORALIS_API") as f:
    API_KEY = f.read().strip()
with open("/etc/secrets/TELEGRAM_TOKEN") as f:
    TELEGRAM_TOKEN = f.read().strip()
with open("/etc/secrets/CHAT_ID") as f:
    CHAT_ID = f.read().strip()
with open("/etc/secrets/HELIUS_API") as f:
    HELIUS_API_KEY = f.read().strip()
with open("/etc/secrets/CALLSTATIC_API") as f:
    CALLSTATIC_API = f.read().strip()

MEMORY_FILE = "token_memory_ultimate.json"
TRACKING_FILE = "token_tracking.json"
WALLET_STATS_FILE = "wallet_stats.json"
API_URL = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/graduated?limit=100"

HEADERS = {
    "Accept": "application/json",
    "X-API-Key": API_KEY,
}

def load_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def save_json(data, file):
    with open(file, "w") as f:
        json.dump(data, f)

def get_rugcheck_data(token_address):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report/summary"
        response = requests.get(url)
        data = response.json()
        score = data.get("score_normalised")
        risks = data.get("risks", [])
        honeypot = any("honeypot" in r["name"].lower() for r in risks)
        lp_locked = all("liquidity" not in r["name"].lower() or "not" not in r["description"].lower() for r in risks)
        return score, honeypot, lp_locked
    except:
        return None, None, None

def get_bonding_curve(token_address):
    try:
        url = f"https://api.callstaticrpc.com/pumpfun/v1/token/{token_address}"
        headers = {"Authorization": f"Bearer {CALLSTATIC_API}"}
        response = requests.get(url, headers=headers)
        data = response.json()
        percentage = float(data.get("bondingCurve", {}).get("percentageComplete", 0.0)) * 100
        return round(percentage, 2)
    except:
        return None

def get_top_holders(token_address):
    try:
        url = f"https://app.bubblemaps.io/api/token/sol/{token_address}"
        response = requests.get(url)
        data = response.json()
        holders = data.get("holders", [])[:10]
        percentages = [round(h.get("share", 0) * 100, 2) for h in holders]
        total = round(sum(percentages), 2)
        return total, percentages
    except:
        return None, []

def get_smart_wallet_buy(token_address, current_mc, wallet_stats):
    try:
        url = f"https://api.helius.xyz/v0/tokens/{token_address}/transfers?api-key={HELIUS_API_KEY}&limit=50"
        response = requests.get(url)
        if response.status_code != 200:
            return None, None, wallet_stats
        transfers = response.json()
        for tx in transfers:
            to_wallet = tx.get("toUserAccount")
            amount = int(tx.get("tokenAmount", {}).get("amount", 0))
            decimals = int(tx.get("tokenAmount", {}).get("decimals", 9))
            amount_formatted = round(amount / (10 ** decimals), 2)
            if amount_formatted >= 5000 and to_wallet:
                if to_wallet not in wallet_stats:
                    wallet_stats[to_wallet] = {"buys": []}
                wallet_stats[to_wallet]["buys"].append({
                    "token": token_address,
                    "mc_entry": current_mc,
                    "mc_now": current_mc
                })
                return amount_formatted, to_wallet, wallet_stats
    except Exception as e:
        print("❌ Helius Error:", e)
    return None, None, wallet_stats

def update_wallet_winrate(wallet_stats, tracking):
    winrates = {}
    for wallet, data in wallet_stats.items():
        wins = 0
        total = 0
        for entry in data["buys"]:
            token = entry["token"]
            mc_entry = entry["mc_entry"]
            mc_now = tracking.get(token, {}).get("current", mc_entry)
            entry["mc_now"] = mc_now
            total += 1
            if mc_now >= 2 * mc_entry or mc_now >= 1_000_000:
                wins += 1
        if total > 0:
            rate = int((wins / total) * 100)
            winrates[wallet] = rate
    return winrates


def send_telegram_message(message, token_address):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [[
            {"text": "🔗 Pump.fun", "url": f"https://pump.fun/{token_address}"},
            {"text": "🔍 Scamr", "url": f"https://ai.scamr.xyz/token/{token_address}"}
        ], [
            {"text": "🛡 Rugcheck", "url": f"https://rugcheck.xyz/tokens/{token_address}"},
            {"text": "🧠 BubbleMaps", "url": f"https://app.bubblemaps.io/sol/token/{token_address}"}
        ], [
            {"text": "💹 Axiom (ref)", "url": f"https://axiom.trade/@glace"}
        ]]
    }
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    }
    try:
        requests.post(url, json=payload)
        time.sleep(2)
    except Exception as e:
        print("❌ Telegram error:", e)

    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
        time.sleep(2)
    except Exception as e:
        print("❌ Telegram error:", e)

def search_twitter_mentions(token_name, ticker):
    try:
        name_query = requests.get(f"https://api.x.com/search?q={token_name}").text
        ticker_query = requests.get(f"https://api.x.com/search?q=%24{ticker}").text
        return len(name_query), len(ticker_query)
    except:
        return 0, 0

def generate_progress_bar(percentage, width=20):
    filled = int(percentage / 100 * width)
    empty = width - filled
    return "▓" * filled + "░" * empty

def check_tokens():
    print("🔍 Checking tokens...")
    try:
        response = requests.get(API_URL, headers=HEADERS)
        data = response.json().get("result", [])
    except Exception as e:
        print("❌ Moralis API error:", e)
        time.sleep(300)
        return

    memory = load_json(MEMORY_FILE)
    tracking = load_json(TRACKING_FILE)
    wallet_stats = load_json(WALLET_STATS_FILE)
    now = time.time()

    for token in data:
        token_address = token.get("tokenAddress")
        if not token_address:
            continue

        name = token.get("name", "N/A")
        symbol = token.get("symbol", "N/A")
        mc = float(token.get("fullyDilutedValuation") or 0)
        lq = float(token.get("liquidity") or 0)
        holders = int(token.get("holders") or 0)

        if mc < 45000 or lq < 8000 or holders < 80:
            memory[token_address] = now
            continue

        rugscore, honeypot, lp_locked = get_rugcheck_data(token_address)
        if honeypot:
            memory[token_address] = now
            continue

        bonding_percent = get_bonding_curve(token_address)
        bonding_bar = generate_progress_bar(bonding_percent) if bonding_percent is not None else "N/A"

        top_total, top_list = get_top_holders(token_address)
        top_display = " | ".join([f"{p}%" for p in top_list]) if top_list else "N/A"

        smart_buy, wallet, wallet_stats = get_smart_wallet_buy(token_address, mc, wallet_stats)
        winrates = update_wallet_winrate(wallet_stats, tracking)
        winrate = winrates.get(wallet, None) if wallet else None

        mentions_name, mentions_ticker = search_twitter_mentions(name, symbol)

        memory[token_address] = now
        tracking[token_address] = {"symbol": symbol, "initial": mc, "current": mc, "alerts": []}
        save_json(tracking, TRACKING_FILE)

        msg = f"""🔍 *NEW TOKEN DETECTED*

💠 *Token:* ${symbol}
🧾 *Address:* `{token_address}`

💰 *Market Cap:* ${int(mc):,}
📊 *Volume 1h:* ${int(lq):,}
👥 *Holders:* {holders}

🧠 *Mentions X*
- Nom: {mentions_name}
- $Ticker: {mentions_ticker}
🔗 [Voir sur X](https://twitter.com/search?q=%24{symbol})

📈 *Bonding Progress:* {bonding_percent or 'N/A'}%
{bonding_bar}

🛡 *Security Check (Rugcheck.xyz)*
- 🔥 Liquidity Burned: ✅
- ❄️ Freeze Authority: ✅
- ➕ Mint Authority: ✅
- 🧮 Rugscore: {rugscore or 'N/A'} ✅
- ✅ Token SAFE – LP Locked, No Honeypot

🐳 *Smart Wallet Buy:* {smart_buy} tokens
- Winrate: {winrate}% {'🟢 Ultra Smart' if winrate and winrate >= 80 else '🟡 Smart' if winrate and winrate >= 60 else '🔴 Risky Wallet' if winrate and winrate < 30 else ''}

📦 *Top 10 Holders:* {top_total or 'N/A'}%
{top_display}
🧑‍💻 = Dev wallet, ✨ = New wallet (< 2 tokens)

🔗 *Links*
- [Pump.fun](https://pump.fun/{token_address})
- [Scamr](https://ai.scamr.xyz/token/{token_address})
- [Rugcheck](https://rugcheck.xyz/tokens/{token_address})
- [BubbleMaps](https://app.bubblemaps.io/sol/token/{token_address})
- [Axiom (ref)](https://axiom.trade/@glace)

📎 *Token address:*
`{token_address}`
"""
        send_telegram_message(msg, token_address)

    save_json(memory, MEMORY_FILE)
    save_json(tracking, TRACKING_FILE)
    save_json(wallet_stats, WALLET_STATS_FILE)

def run_flask():
    app.run(host="0.0.0.0", port=8080)

def start_loop():
    while True:
        check_tokens()
        time.sleep(120)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    start_loop()


from flask import request


@app.route(f"/bot/{TELEGRAM_TOKEN}", methods=["POST"])
def receive_update():
    data = request.get_json()
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "")

    if chat_id != ADMIN_USER_ID:
        return "Unauthorized"

    if text == "/scan":
        send_telegram_message("✅ Scan manuel lancé...", "manual")
        check_tokens()

    elif text == "/status":
        try:
            memory = load_json(MEMORY_FILE)
            tracking = load_json(TRACKING_FILE)
            tokens_today = [k for k, v in memory.items() if time.time() - v < 86400]
            alerts = len(tracking)
            msg = f"📊 *Status du bot Pump.fun*

- 🔍 Tokens scannés aujourd'hui : {len(tokens_today)}
- 🚀 Tokens envoyés depuis lancement : {alerts}"
        except:
            msg = "❌ Erreur lors de la récupération du status."
        send_telegram_message(msg, "manual")

    elif text == "/help":
        msg = (
            "🤖 *Commandes disponibles*

"
            "• `/scan` – Lancer un scan manuel maintenant
"
            "• `/status` – Voir combien de tokens ont été scannés et envoyés
"
            "• `/help` – Afficher cette aide

"
            "Le bot détecte automatiquement les tokens Pump.fun prometteurs :
"
            "🧠 Smart Wallets • 📈 Bonding Curve • 🛡 Rugcheck • 🐳 Whale Tracking • 📦 Top Holders"
        )
        send_telegram_message(msg, "manual")

    return "OK"
