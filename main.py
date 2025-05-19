import os
import time
import json
import requests
from datetime import datetime
from flask import Flask
from threading import Thread

app = Flask(__name__)

with open("/etc/secrets/MORALIS_API") as f:
    API_KEY = f.read().strip()
with open("/etc/secrets/TELEGRAM_TOKEN") as f:
    TELEGRAM_TOKEN = f.read().strip()
with open("/etc/secrets/CHAT_ID") as f:
    CHAT_ID = f.read().strip()
with open("/etc/secrets/HELIUS_API") as f:
    HELIUS_API_KEY = f.read().strip()

MEMORY_FILE = "token_memory_ultimate.json"
TRACKING_FILE = "token_tracking.json"
WALLET_STATS_FILE = "wallet_stats.json"
API_URL = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/graduated?limit=100"

HEADERS = {
    "Accept": "application/json",
    "X-API-Key": API_KEY,
}

def get_rugcheck_data(token_address):
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report/summary"
        response = requests.get(url)
        data = response.json()
        score = data.get("score_normalised")
        risks = data.get("risks", [])
        holders = data.get("totalHolders", 0)
        honeypot = any("honeypot" in r["name"].lower() for r in risks)
        lp_locked = all("liquidity" not in r["name"].lower() or "not" not in r["description"].lower() for r in risks)
        return score, honeypot, lp_locked, holders
    except:
        return None, None, None, 0

def load_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def save_json(data, file):
    with open(file, "w") as f:
        json.dump(data, f)

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

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
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

def check_tokens():
    print("🔍 Checking tokens...")
    try:
        response = requests.get(API_URL, headers=HEADERS)
        data = response.json().get("result", [])
    except Exception as e:
        print("❌ Moralis API error:", e)
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

        rugscore, honeypot, lp_locked, holders = get_rugcheck_data(token_address)
        if honeypot:
            memory[token_address] = now
            continue

        smart_buy, wallet, wallet_stats = get_smart_wallet_buy(token_address, mc, wallet_stats)
        winrates = update_wallet_winrate(wallet_stats, tracking)
        winrate = winrates.get(wallet, None) if wallet else None

        mentions_name, mentions_ticker = search_twitter_mentions(name, symbol)

        memory[token_address] = now
        tracking[token_address] = {"symbol": symbol, "initial": mc, "current": mc, "alerts": []}
        save_json(tracking, TRACKING_FILE)

        msg = "*🚀 NEW TOKEN DETECTED*\n"
        msg += f"*Token:* ${symbol}\n"
        msg += f"*Market Cap:* ${int(mc):,} | *Volume 1h:* ${int(lq):,}\n"
        msg += f"*Holders:* {holders}\n"
        msg += f"🧠 *Mentions X* – Nom: {mentions_name} | $Ticker: {mentions_ticker}\n"
        msg += f"🔗 [Voir sur X](https://twitter.com/search?q=%24{symbol})\n"

        if rugscore is not None:
            msg += f"*Rugscore:* {rugscore} ✅\n"
        if lp_locked and not honeypot:
            msg += "✅ Token SAFE – LP Locked, No Honeypot\n"

        if smart_buy:
            msg += f"🐳 Smart Wallet Buy: {smart_buy} tokens"
            if winrate is not None:
                msg += f" (WinRate: {winrate}%)\n"
                if winrate >= 80:
                    msg += "🟢 Ultra Smart\n"
                elif winrate >= 60:
                    msg += "🟡 Smart\n"
                elif winrate < 30:
                    msg += "🔴 Risky Wallet\n"
            else:
                msg += "\n"

        msg += f"\n🔗 [Pump.fun](https://pump.fun/{token_address})"
        msg += f" | [Scamr](https://ai.scamr.xyz/token/{token_address})"
        msg += f" | [Rugcheck](https://rugcheck.xyz/tokens/{token_address})"
        msg += f" | [BubbleMaps](https://app.bubblemaps.io/sol/token/{token_address})"
        msg += f" | [Axiom](https://axiom.trade/@glace)\n"
        msg += f"*Token address:* `{token_address}`"

        send_telegram_message(msg)

    save_json(memory, MEMORY_FILE)
    save_json(tracking, TRACKING_FILE)
    save_json(wallet_stats, WALLET_STATS_FILE)

def run_flask():
    app.run(host="0.0.0.0", port=8080)

def start_loop():
    while True:
        check_tokens()
        time.sleep(120)  # Pause de 2 minutes entre les scans

if __name__ == "__main__":
    Thread(target=run_flask).start()
    start_loop()
