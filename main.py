import os
import time
import json
import requests
from datetime import datetime, time as dtime
from flask import Flask
from threading import Thread

app = Flask(__name__)

with open("/etc/secrets/MORALIS_API") as f:
    API_KEY = f.read().strip()
with open("/etc/secrets/TELEGRAM_TOKEN") as f:
    TELEGRAM_TOKEN = f.read().strip()
with open("/etc/secrets/CHAT_ID") as f:
    CHAT_ID = f.read().strip()

MEMORY_FILE = "token_memory_ultimate.json"
TRACKING_FILE = "token_tracking.json"
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
    except Exception as e:
        return None, None, None, 0

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
        time.sleep(2)
    except Exception as e:
        print("❌ Telegram error:", e)

def load_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def save_json(data, file):
    with open(file, "w") as f:
        json.dump(data, f)

def is_new_token(token_address, memory):
    return token_address not in memory

def send_marketcap_gain_alert(token_address, data):
    symbol = data["symbol"]
    initial = data["initial"]
    current = data["current"]
    gain = current - initial
    for threshold in [50000, 100000, 200000, 500000]:
        if threshold not in data["alerts"] and gain >= threshold:
            msg = f"📈 Token ${symbol} is up by +${threshold:,} since first detection!\nInitial: ${initial:,} → Now: ${current:,}"
            send_telegram_message(msg)
            data["alerts"].append(threshold)
            return

def send_daily_winners():
    tracking = load_json(TRACKING_FILE)
    gainers = []
    for addr, t in tracking.items():
        gain = t["current"] - t["initial"]
        if gain > 0:
            gainers.append({"symbol": t["symbol"], "initial": t["initial"], "current": t["current"], "gain": gain})
    top = sorted(gainers, key=lambda x: x["gain"], reverse=True)[:3]
    if not top:
        send_telegram_message("📊 No tokens showed significant gains in the last 12h.")
        return
    msg = "📊 *Daily Winners (last 12h)*\n"
    for i, t in enumerate(top, 1):
        msg += f"{i}. ${t['symbol']}: ${t['initial']:,} → ${t['current']:,} (+${t['gain']:,})\n"
    send_telegram_message(msg)

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
    now = time.time()

    for token in data:
        token_address = token.get("tokenAddress")
        if not token_address:
            continue

        name = token.get("name", "N/A")
        symbol = token.get("symbol", "N/A")
        mc = float(token.get("fullyDilutedValuation") or 0)
        lq = float(token.get("liquidity") or 0)

        if token_address in tracking:
            tracking[token_address]["current"] = mc
            send_marketcap_gain_alert(token_address, tracking[token_address])

        if not is_new_token(token_address, memory):
            continue

        if mc < 20000 or lq < 10000:
            memory[token_address] = now
            continue

        rugscore, honeypot, lp_locked, holders = get_rugcheck_data(token_address)
        if honeypot is True:
            memory[token_address] = now
            continue

        memory[token_address] = now
        tracking[token_address] = {"symbol": symbol, "initial": mc, "current": mc, "alerts": []}
        save_json(tracking, TRACKING_FILE)

        msg = "*NEW TOKEN DETECTED*\n"
        msg += f"*Token:* ${symbol}\n"
        msg += f"*Market Cap:* {'{:,}'.format(int(mc))} | *Volume 1h:* {'{:,}'.format(int(lq))}\n"
        msg += f"*Holders:* {holders}\n"
        if rugscore is not None:
            msg += f"*Rugscore:* {rugscore} ✅\n"
        if lp_locked and not honeypot:
            msg += "✅ Token SAFE – LP Locked, No Honeypot\n"
        msg += f"➤ [Pump.fun](https://pump.fun/{token_address}) | [Scamr](https://ai.scamr.xyz/token/{token_address}) | [Rugcheck](https://rugcheck.xyz/tokens/{token_address}) | [BubbleMaps](https://app.bubblemaps.io/sol/token/{token_address}) | [Twitter Search](https://twitter.com/search?q={symbol}&src=typed_query&f=live) | [Trade on Axiom](https://axiom.trade/@glace)\n"
        msg += f"*Token adresse:* `{token_address}`"
        send_telegram_message(msg)

    save_json(memory, MEMORY_FILE)
    save_json(tracking, TRACKING_FILE)

    now_time = datetime.now().time()
    if now_time.hour == 6 and now_time.minute == 0:
        send_daily_winners()
    elif now_time.hour == 20 and now_time.minute == 0:
        send_daily_winners()

def run_flask():
    app.run(host="0.0.0.0", port=8080)

def start_loop():
    while True:
        check_tokens()
        time.sleep(60)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    start_loop()
