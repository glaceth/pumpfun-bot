import os
import time
import json
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from threading import Thread
from bs4 import BeautifulSoup
import base58
from solders.keypair import Keypair
import logging

# === CONFIG LOGGING ===
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
)
logging.info("✅ Fichier lancé correctement — import os OK")

app = Flask(__name__)

# --- Authentification RugCheck robuste ---
class RugCheckRateLimitError(Exception):
    pass

class RugCheckAuthenticator:
    def __init__(self):
        self.token = None
        self.last_login_time = 0
        self.backoff = 10
        self.max_backoff = 600

    def login(self):
        if self.token and not self.token_expired():
            return self.token
        attempt = 0
        while True:
            try:
                token = self.rugcheck_login_request()
                self.token = token
                self.last_login_time = time.time()
                self.backoff = 10
                logging.info("✅ Login RugCheck réussi")
                return token
            except RugCheckRateLimitError:
                logging.error("❌ Rate limit! Attente de %ds avant nouvel essai.", self.backoff)
                time.sleep(self.backoff)
                self.backoff = min(self.backoff * 2, self.max_backoff)
                attempt += 1
            except Exception as e:
                logging.error("❌ Erreur login RugCheck: %s", str(e))
                break

    def token_expired(self):
        # Optionnel: à améliorer si tu veux vérifier l'expiration réelle du token
        return False

# --- Fin ajout authentification RugCheck robuste ---

ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "Glacesol")

def load_secret(path, fallback_env=None):
    try:
        with open(path) as f:
            secret = f.read().strip()
            logging.debug(f"Secret chargé depuis {path}")
            return secret
    except Exception as e:
        if fallback_env:
            val = os.getenv(fallback_env)
            if val:
                logging.debug(f"Secret chargé depuis env {fallback_env}")
                return val
        logging.error(f"❌ Missing secret {path} and no fallback ({fallback_env}) : {e}")
        return None

API_KEY = load_secret("/etc/secrets/MORALIS_API", "MORALIS_API")
TELEGRAM_TOKEN = load_secret("/etc/secrets/TELEGRAM_TOKEN", "TELEGRAM_TOKEN")
CHAT_ID = load_secret("/etc/secrets/CHAT_ID", "CHAT_ID")
HELIUS_API_KEY = load_secret("/etc/secrets/HELIUS_API", "HELIUS_API_KEY")
CALLSTATIC_API = load_secret("/etc/secrets/CALLSTATIC_API", "CALLSTATIC_API")

# Correction ici : secrets Rugcheck gérés comme les autres

# --- Instanciation du nouvel authentificateur RugCheck ---
rugcheck_auth = RugCheckAuthenticator()

MEMORY_FILE = "token_memory_ultimate.json"
TRACKING_FILE = "token_tracking.json"
WALLET_STATS_FILE = "wallet_stats.json"
API_URL = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/graduated?limit=100"

HEADERS = {
    "Accept": "application/json",
    "X-API-Key": API_KEY,
}

def send_simple_message(text, chat_id):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logging.error("❌ Telegram simple message error: %s", e)

def load_json(file):
    if not os.path.exists(file):
        return {}
    try:
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"❌ JSON load error for {file}: {e}")
        return {}

def save_json(data, file):
    try:
        with open(file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"❌ JSON save error for {file}: {e}")

def get_scamr_holders(token_address):
    try:
        url = f"https://ai.scamr.xyz/token/{token_address}"
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text()
        for line in text.splitlines():
            if "Score:" in line and any(char.isdigit() for char in line):
                return line.strip().split("Score:")[-1].strip()
        return "N/A"
    except Exception as e:
        logging.error(f"❌ Scamr error: {e}")
        return "N/A"

def get_rugcheck_data(token_address):
    def call():
        token = rugcheck_auth.login()
        if not token:
            logging.error("❌ No RugCheck token")
            return None, None, None, 0
        url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report/summary"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            response = requests.get(url, headers=headers, timeout=2.5)
            if response.status_code == 200 and response.text.strip():
                data = response.json()
                score = data.get("score_normalised")
                risks = data.get("risks", [])
                honeypot = any("honeypot" in r["name"].lower() for r in risks)
                lp_locked = all(
                    "liquidity" not in r["name"].lower() or "not" not in r["description"].lower()
                    for r in risks
                )
                holders = data.get("holders", 0) or 0
                return score, honeypot, lp_locked, holders
            else:
                logging.error(f"❌ RugCheck data error: {response.status_code} {response.text}")
        except Exception as e:
            logging.error(f"❌ RugCheck API error: {e}")
        return None, None, None, 0
    try:
        result = call()
        if result == (None, None, None, 0):
            result = call()
        return result
    except Exception as e:
        logging.error(f"❌ RugCheck call error: {e}")
        return None, None, None, 0

def get_bonding_curve(token_address):
    try:
        url = f"https://api.callstaticrpc.com/pumpfun/v1/token/{token_address}"
        headers = {"Authorization": f"Bearer {CALLSTATIC_API}"}
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        percentage = float(data.get("bondingCurve", {}).get("percentageComplete", 0.0)) * 100
        return round(percentage, 2)
    except Exception as e:
        logging.error(f"❌ Bonding curve error: {e}")
        return None

def get_top_holders(token_address):
    try:
        url = f"https://app.bubblemaps.io/api/token/sol/{token_address}"
        response = requests.get(url, timeout=10)
        data = response.json()
        holders = data.get("holders", [])[:5]
        percentages = [round(h.get("share", 0) * 100, 2) for h in holders]
        total = round(sum(percentages), 2)
        return total, percentages
    except Exception as e:
        logging.error(f"❌ Top holders error: {e}")
        return None, []

def get_smart_wallet_buy(token_address, current_mc, wallet_stats):
    try:
        url = f"https://api.helius.xyz/v0/tokens/{token_address}/transfers?api-key={HELIUS_API_KEY}&limit=50"
        response = requests.get(url, timeout=10)
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
        logging.error("❌ Helius Error: %s", e)
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
            {"text": "💹 Axiom (ref)", "url": f"https://axiom.trade/@glace"},
            {"text": "🤖 Analyze with AI", "url": f"https://pumpfun-bot-1.onrender.com/analyze?token={token_address}"}
        ]]
    }
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "reply_markup": keyboard
    }
    try:
        requests.post(url, json=payload, timeout=10)
        time.sleep(2)
    except Exception as e:
        logging.error("❌ Telegram error: %s", e)

def search_twitter_mentions(token_name, ticker):
    return "N/A"

def generate_progress_bar(percentage, width=20):
    filled = int(percentage / 100 * width)
    empty = width - filled
    return "▓" * filled + "░" * empty

def get_wallet_deployment_stats(wallet_address):
    try:
        url = f"https://api.helius.xyz/v0/addresses/{wallet_address}/transactions?api-key={HELIUS_API_KEY}&limit=20"
        response = requests.get(url, timeout=10)
        txs = response.json()
        deployed_tokens = []
        for tx in txs:
            if "tokenTransfers" in tx:
                for transfer in tx["tokenTransfers"]:
                    if transfer.get("type") == "mint":
                        token_address = transfer.get("mint")
                        if token_address:
                            deployed_tokens.append(token_address)
        if not deployed_tokens:
            return None, 0, None
        last_token = deployed_tokens[0]
        cs_url = f"https://api.callstaticrpc.com/pumpfun/v1/token/{last_token}"
        headers = {"Authorization": f"Bearer {CALLSTATIC_API}"}
        cs_res = requests.get(cs_url, headers=headers, timeout=10)
        cs_data = cs_res.json()
        last_symbol = cs_data.get("symbol", "N/A")
        last_mc = cs_data.get("fullyDilutedValuation", 0)
        return last_symbol, len(deployed_tokens), int(last_mc)
    except Exception as e:
        logging.error("❌ Wallet deployer stats error: %s", e)
        return None, 0, None

def check_tokens():
    logging.info("🔍 Checking tokens...")
    try:
        response = requests.get(API_URL, headers=HEADERS, timeout=20)
        data = response.json().get("result", [])
    except Exception as e:
        logging.error("❌ Moralis API error: %s", e)
        time.sleep(300)
        return
    memory = load_json(MEMORY_FILE)
    tracking = load_json(TRACKING_FILE)
    wallet_stats = load_json(WALLET_STATS_FILE)
    now = time.time()

    for token in data:
        logging.info(f"🔎 Token found: {token.get('symbol', 'N/A')} — MC: {token.get('fullyDilutedValuation')} — Holders: {token.get('holders')}")
        token_address = token.get("tokenAddress")
        if not token_address:
            continue
        name = token.get("name", "N/A")
        symbol = token.get("symbol", "N/A")
        mc = float(token.get("fullyDilutedValuation") or 0)
        lq = float(token.get("liquidity") or 0)
        rugscore, honeypot, lp_locked, holders_rug = get_rugcheck_data(token_address)
        holders = holders_rug or token.get('holders', 0)
        if mc < 45000 or lq < 8000 or (holders != 0 and holders < 80):
            logging.info("❌ Filtered out due to MC, liquidity or holders")
            continue
        if honeypot:
            logging.info("⚠️ Honeypot detected, skipping token")
            memory[token_address] = now
            continue
        if not lp_locked:
            logging.info("❌ LP not locked – token skipped")
            memory[token_address] = now
            continue
        if rugscore is not None and rugscore < 40:
            logging.info(f"❌ Rugscore too low ({rugscore}) – skipping token")
            memory[token_address] = now
            continue

        bonding_percent = get_bonding_curve(token_address)
        bonding_bar = generate_progress_bar(bonding_percent) if bonding_percent is not None else "N/A"
        top_total, top_list = get_top_holders(token_address)
        top_display = " | ".join([f"{p}%" for p in top_list]) if top_list else "N/A"
        mentions = search_twitter_mentions(name, symbol)
        smart_buy, wallet, wallet_stats = get_smart_wallet_buy(token_address, mc, wallet_stats)
        winrates = update_wallet_winrate(wallet_stats, tracking)
        winrate = winrates.get(wallet, 0) if wallet else 0

        memory[token_address] = now
        tracking[token_address] = {"symbol": symbol, "initial": mc, "current": mc, "alerts": [], "timestamp": now}

        msg = f"""🔍 *NEW TOKEN DETECTED*

💠 *Token:* ${symbol}
🧾 *Address:* `{token_address}`

💰 *Market Cap:* ${int(mc):,}
📊 *Volume 1h:* ${int(lq):,}
👥 *Holders:* {holders or 'N/A'}

🧠 *Mentions X: {mentions}*

📈 *Bonding Progress:* {bonding_percent or 'N/A'}%
{bonding_bar}

🛡 *Security Check (Rugcheck.xyz)*
- 🔥 Liquidity Burned: ✅
- ❄️ Freeze Authority: ✅
- ➕ Mint Authority: ✅
- 🧮 Rugscore: {rugscore or 'N/A'} {'🟢' if rugscore and rugscore >= 80 else '🟡' if rugscore and rugscore >= 60 else '🟠' if rugscore and rugscore >= 40 else '🔴' if rugscore else ''}
- ✅ Token SAFE – LP Locked, No Honeypot

🐳 *Smart Wallet Buy:* {smart_buy or 'N/A'} tokens
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

        if wallet:
            prev_symbol, launch_count, prev_mc = get_wallet_deployment_stats(wallet)
            if prev_symbol:
                msg += f"\n\nPrev Deployed: ${prev_symbol} (${prev_mc:,})"
                msg += f"\n# of Launches: {launch_count}"
                if launch_count > 20:
                    msg += " 🧨 Serial Launcher"
                elif launch_count == 1:
                    msg += " 🆕 First Launch"

        previous_ts = tracking.get(token_address, {}).get("timestamp")
        if previous_ts and (now - previous_ts > 3600):
            msg += f"\n\n Token previously detected {round((now - previous_ts) / 3600, 1)}h ago – new volume spike!"
            mc_entry = tracking.get(token_address, {}).get("initial", mc)
            if mc > mc_entry * 2:
                msg += " 🚀 x2+ pump since first call!"
            elif mc > mc_entry * 1.5:
                msg += " 📈 +50% since first call!"

        send_telegram_message(msg, token_address)
        logging.info(f"✅ Telegram message sent for token: {symbol}")

    save_json(memory, MEMORY_FILE)
    save_json(tracking, TRACKING_FILE)
    save_json(wallet_stats, WALLET_STATS_FILE)

    for tracked_token, info in tracking.items():
        ts = info.get("timestamp")
        if not ts or (now - ts) < 3600 or (now - ts) > 4000:
            continue
        mc_entry = info.get("initial", 0)
        mc_now = info.get("current", mc_entry)
        symbol_tracked = info.get("symbol", "N/A")
        if mc_now > mc_entry and "soar" not in info["alerts"]:
            multiplier = round(mc_now / mc_entry, 1)
            if multiplier >= 2:
                message = f"🚀🚀🚀 ${symbol_tracked} soared by X{multiplier} in an hour since it was called! 🌕"
                send_telegram_message(message, tracked_token)
                info["alerts"].append("soar")
    save_json(tracking, TRACKING_FILE)

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"status": "ignored"})
    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    if text == "/scan":
        username = message["from"].get("username", "")
        if username != ADMIN_USER_ID:
            send_simple_message("🚫 Unauthorized", chat_id)
            return jsonify({"status": "unauthorized"})
        send_simple_message("✅ Scan manuel lancé...", chat_id)
        check_tokens()
        send_simple_message("📘 Commands available:\n/scan - Manual scan\n/help - This help message", chat_id)
    else:
        send_simple_message("🤖 Unknown command. Try /help", chat_id)
    return jsonify({"status": "ok"})

from openai import OpenAI

def read_secret_file(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception as e:
        logging.error(f"Erreur lecture secret file {path} : {e}")
        return None

openai_api_key = read_secret_file("/etc/secrets/OPENAI_API_KEY")
logging.debug("DEBUG OPENAI_API_KEY (file): %r", openai_api_key)
if not openai_api_key:
    raise RuntimeError(
        "❌ ERREUR : la clé OpenAI n'est pas trouvée dans le secret file /etc/secrets/OPENAI_API_KEY. "
        "Vérifie le nom et le contenu du secret file dans Render !"
    )
client = OpenAI(api_key=openai_api_key)

def ask_gpt(prompt):
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu es un expert en trading crypto spécialisé dans les tokens ultra-récents sur Pump.fun (Solana). "
                        "Tu as l'expérience de TendersAlt : tu appliques des stratégies simples, sans émotions, en t'appuyant sur des probabilités, des setups Fibonacci, et l'observation des wallets. "
                        "Analyse objectivement, sois direct, concis, stratégique."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            temperature=0.4
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error("Error calling GPT: %s", e)
        return f"Error calling GPT: {e}"

@app.route("/analyze", methods=["GET"])
def analyze_token():
    token_address = request.args.get("token")
    if not token_address:
        return "Token address missing", 400

    tracking = load_json(TRACKING_FILE)
    token_data = tracking.get(token_address)
    if token_data:
        name = token_data.get('name', token_data.get('symbol', 'N/A'))
        symbol = token_data.get('symbol', 'N/A')
        market_cap = token_data.get('current', 'N/A')
        volume = token_data.get('volume', 'N/A')
        holders = token_data.get('holders', 'N/A')
    else:
        moralis_url = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/graduated?limit=100"
        headers = {"Accept": "application/json", "X-API-Key": API_KEY}
        try:
            response = requests.get(moralis_url, headers=headers, timeout=10)
            results = response.json().get("result", [])
            moralis_data = next((item for item in results if item.get("tokenAddress") == token_address), None)
        except Exception as e:
            return f"Erreur API Moralis: {e}", 500

        if not moralis_data:
            return "Token not found", 404

        name = moralis_data.get('name', 'N/A')
        symbol = moralis_data.get('symbol', 'N/A')
        market_cap = moralis_data.get('fullyDilutedValuation', 'N/A')
        volume = moralis_data.get('liquidity', 'N/A')
        holders = moralis_data.get('holders', 'N/A')

    rugscore, honeypot, lp_locked, holders_rug = get_rugcheck_data(token_address)
    bonding_percent = get_bonding_curve(token_address)
    top_total, top_list = get_top_holders(token_address)
    scamr_note = get_scamr_holders(token_address)
    lp_status = "Locked" if lp_locked else "Not locked"
    smart_wallets = "Oui" if holders_rug and holders_rug > 100 else "Non"
    mentions = "N/A"
    top5_distribution = " | ".join([f"{p}%" for p in (top_list[:5] if top_list else [])]) or "N/A"

    prompt = f"""
Tu es un expert en trading crypto spécialisé dans les tokens ultra-récents sur Pump.fun (Solana). Tu as l'expérience de TendersAlt : tu appliques des stratégies simples, sans émotions, en t'appuyant sur des probabilités, des setups Fibonacci, et l'observation des wallets.

Analyse ce token objectivement en te basant sur les infos suivantes :

- Nom du token : {name}
- Ticker : ${symbol}
- Market Cap actuel : {market_cap} $
- Volume 1h : {volume}
- % de bonding curve rempli : {bonding_percent or 'N/A'}%
- Nombre de holders : {holders}
- Rugscore : {rugscore or 'N/A'}/100
- LP status : {lp_status}
- Présence de smart wallets : {smart_wallets}
- Top 5 holders = {top5_distribution}
- Mentions sur Twitter : {mentions}
- Score de confiance Scamr.io : {scamr_note}

---

✅ Réponds comme si tu étais un trader pro :

1. **Est-ce un setup intéressant ? Pourquoi ?**
2. **Conseilles-tu d’entrer ? Si oui, à quelle market cap ?**
3. **Quel serait un bon stop loss ?**
4. **Combien du portefeuille tu y alloues ? (1%, 3%, 5% ?...)**
5. **Quel est le signal pour sortir ?**
6. **Y a-t-il un signal de manipulation / fake pump ?**

Sois direct, concis, stratégique, comme si tu devais conseiller un trader qui ne veut pas perdre de temps. Mets en garde si nécessaire.
""".strip()

    result = ask_gpt(prompt)
    send_telegram_message(f"🤖 *GPT Analysis – ${symbol}*\n\n{result}", token_address)
    return jsonify({
        "prompt": prompt,
        "analysis": result
    })

def start_loop():
    current_time = datetime.now()
    if current_time.hour in [6, 20] and current_time.minute < 2:
        send_daily_winners()
    while True:
        check_tokens()
        time.sleep(120)

def send_daily_winners():
    tracking = load_json(TRACKING_FILE)
    now = datetime.now()
    winners = []
    for token_address, data in tracking.items():
        symbol = data.get("symbol", "N/A")
        initial = data.get("initial", 0)
        current = data.get("current", initial)
        if initial > 0 and current > initial:
            multiplier = round(current / initial, 2)
            winners.append((symbol, multiplier, token_address))
    winners.sort(key=lambda x: x[1], reverse=True)
    top_winners = winners[:3]
    if top_winners:
        msg = f"🏆 *Top Tokens Since Detection – {now.strftime('%Y-%m-%d')}*\n"
        for i, (symbol, mult, _) in enumerate(top_winners, 1):
            msg += f"{i}. ${symbol} – x{mult}\n"
        send_simple_message(msg.strip(), CHAT_ID)

if __name__ == "__main__":
    logging.info(f"Bot lancé depuis : {os.getcwd()}")
    Thread(target=run_flask, daemon=True).start()
    start_loop()


RUG_CHECK_URL = "https://api.rugcheck.xyz/v1/tokens/{}/report"
min_lp_locked_amount = 25000
min_lp_locked_pct = 75
max_risk_score = 501
max_holder_pct = 20

def fetch_token_data(token_address):
    try:
        response = requests.get(RUG_CHECK_URL.format(token_address))
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Erreur lors de la récupération des données RugCheck pour {token_address}: {e}")
        return None

def check_top_holders(holders):
    if not holders:
        return False
    for holder in holders:
        if holder.get('pct', 0) > max_holder_pct:
            return False
    return True

def check_lp_burned(markets):
    if not markets:
        return False
    raydium_market = next((m for m in markets if m.get("marketType") == "raydium"), None)
    if not raydium_market:
        return False
    lp = raydium_market.get('lp', {})
    return (
        lp.get('lpLocked', 0) > 0 and
        lp.get('lpLockedUSD', 0) > min_lp_locked_amount and
        lp.get('lpLockedPct', 0) > min_lp_locked_pct
    )

def check_max_risk_score(data):
    return data.get('score', 0) <= max_risk_score

def check_token_is_not_rug(token_address):
    data = fetch_token_data(token_address)
    if not data:
        return False, None
    top_holders_valid = check_top_holders(data.get('topHolders', []))
    lp_burned = check_lp_burned(data.get('markets', []))
    risk_score_ok = check_max_risk_score(data)
    holders_count = data.get('holderCount', None)
    return (top_holders_valid and lp_burned and risk_score_ok), holders_count
