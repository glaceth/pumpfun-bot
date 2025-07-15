import os
import time
import json
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from threading import Thread
from bs4 import BeautifulSoup
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
)
logging.info("✅ Fichier lancé correctement — import os OK")

def save_for_analysis(token_name):
    try:
        with open("tokens_to_analyze.json", "r") as f:
            tokens = json.load(f)
    except FileNotFoundError:
        tokens = []

    if token_name not in tokens:
        tokens.append(token_name)
        with open("tokens_to_analyze.json", "w") as f:
            json.dump(tokens, f)

app = Flask(__name__)

@app.route("/scan_tokens", methods=["POST"])
def scan_tokens():
    """
    Endpoint appelé par Tendy API pour lancer un scan des tokens.
    """
    # Lance le scan en thread pour ne pas bloquer la requête HTTP
    Thread(target=check_tokens).start()
    return jsonify({"status": "scan lancé"})

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
        return None
    except Exception as e:
        logging.error(f"❌ Scamr error: {e}")
        return None

def get_rugcheck_data(token_address):
    url = f"https://api.rugcheck.xyz/v1/tokens/{token_address}/report"
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            score = data.get("score_normalised") or data.get("score")
            honeypot = False
            risks = data.get("risks", [])
            for r in risks:
                if "honeypot" in r.get("name", "").lower():
                    honeypot = True
            lp_locked = False
            for market in data.get("markets", []):
                lp = market.get("lp", {})
                if lp.get("lpLockedPct", 0) >= 75 and lp.get("lpLockedUSD", 0) > 2500:
                    lp_locked = True
            holders = data.get("totalHolders") or data.get("holders")
            volume = None
            for market in data.get("markets", []):
                lp = market.get("lp", {})
                if lp.get("quoteUSD"):
                    volume = lp.get("quoteUSD")
                    break
            if not volume:
                volume = data.get("totalMarketLiquidity")
            top_holders = []
            for h in data.get("topHolders", [])[:5]:
                pct = round(h.get("pct", 0), 1)
                top_holders.append(pct)
            freeze_removed = data.get("freezeAuthority") is None
            mint_revoked = data.get("mintAuthority") is None
            risk_label = data.get("risk_label") or data.get("riskLevel") or data.get("risk_level")
            return score, honeypot, lp_locked, holders, volume, top_holders, freeze_removed, mint_revoked, risk_label
        else:
            logging.error(f"RugCheck public error: {resp.status_code} {resp.text}")
            return None, None, None, None, None, [], None, None, None
    except Exception as e:
        logging.error(f"RugCheck API error: {e}")
        return None, None, None, None, None, [], None, None, None

def get_rugcheck_holders_with_retry(token_address, max_retries=15, delay=2):
    for attempt in range(max_retries):
        _, _, _, holders, *_ = get_rugcheck_data(token_address)
        if holders and holders > 0:
            return holders
        time.sleep(delay)
    return None

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
        return percentages
    except Exception as e:
        logging.error(f"❌ Top holders error: {e}")
        return []

def send_telegram_message(message, token_address):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    keyboard = {
        "inline_keyboard": [[
            {"text": "🤖 Analyze with AI", "url": f"https://pumpfun-bot-1.onrender.com/analyze?token={token_address}"}
        ], [
            {"text": "🌐 Pump.fun", "url": f"https://pump.fun/{token_address}"},
            {"text": "🧪 Scam Check", "url": f"https://ai.scamr.xyz/token/{token_address}"}
        ], [
            {"text": "🔍 RugCheck", "url": f"https://rugcheck.xyz/tokens/{token_address}"},
            {"text": "🗺️ BubbleMaps", "url": f"https://app.bubblemaps.io/sol/token/{token_address}"}
        ], [
            {"text": "📊 Axiom (Ref)", "url": f"https://axiom.trade/@glace"}
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

def search_twitter_mentions(symbol):
    if symbol:
        return f"https://twitter.com/search?q=%24{symbol}&src=typed_query"
    return ""

# AJOUT : envoi à une API externe (Tendy bot ou autre)
def send_to_tendy_api(tokens, analyses=None):
    api_base = "https://tendy-api.onrender.com"  # ton URL API
    try:
        # Envoie la liste complète des tokens
        response_tokens = requests.post(f"{api_base}/tokens", json=tokens, timeout=10)
        logging.info(f"✅ Tokens envoyés à l'API Tendy: {response_tokens.status_code}")

        # Si tu veux aussi envoyer l'historique des analyses
        if analyses is not None:
            response_analyses = requests.post(f"{api_base}/analyses_history", json=analyses, timeout=10)
            logging.info(f"✅ Analyses envoyées à l'API Tendy: {response_analyses.status_code}")

    except Exception as e:
        logging.error(f"❌ Erreur d'envoi à l'API Tendy: {e}")

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
        token_address = token.get("tokenAddress")
        if not token_address:
            continue
        name = token.get("name", "")
        symbol = token.get("symbol", "")
        mc = float(token.get("fullyDilutedValuation") or 0)
        lq = float(token.get("liquidity") or 0)
        created_at = token.get("createdAt") or token.get("timestamp") or token.get("launchDate")
        launch_str = ""
        if created_at:
            try:
                if int(created_at) > 1e12:
                    created_at = int(created_at) / 1000
                seconds = int(now - float(created_at))
                minutes = seconds // 60
                hours = minutes // 60
                if hours > 0:
                    launch_info = f"{hours}h {minutes % 60}min"
                else:
                    launch_info = f"{minutes}min"
                launch_str = f"⏰ Launch: {launch_info} ago\n"
            except Exception as e:
                logging.warning(f"Erreur calcul launch_str: {e}")

        rugscore, honeypot, lp_locked, holders, volume, top_holders, freeze_removed, mint_revoked, risk_label = get_rugcheck_data(token_address)
        logging.info(f"🔎 Token found: {symbol} — MC: {mc} — Holders: {holders}")

        # --- FILTRE TOP HOLDER > 30% ---
        if top_holders and top_holders[0] >= 30:
            logging.info(f"❌ Top holder >= 30% ({top_holders[0]}%) – skipping token")
            memory[token_address] = now
            continue
        # --- FIN FILTRE ---

        if mc < 45000 or lq < 8000 or (holders is not None and holders < 80):
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

        # -------- PATCH RUGSCORE < 40 -------- #
        attention = ""
        if rugscore is not None and rugscore < 40:
            if holders is not None and holders >= 500:
                logging.info(f"⚠️ Rugscore faible ({rugscore}) mais {holders} holders, token envoyé avec avertissement")
                attention = f"\n⚠️ *ATTENTION : RugScore faible ({rugscore}/100) — DYOR !*"
            else:
                logging.info(f"❌ Rugscore too low ({rugscore}) – skipping token (holders: {holders})")
                memory[token_address] = now
                continue
        elif rugscore is not None and rugscore >= 70:
            attention = f"\n✅ *RugScore élevé ({rugscore}/100) – plutôt rassurant, mais DYOR !*"
        # -------- FIN PATCH -------- #

        msg = "🚨 *New Token Detected!*\n\n"
        if name: msg += f"💰 *Name:* {name}\n"
        if symbol: msg += f"🪙 *Symbol:* ${symbol}\n"
        if mc: msg += f"📈 *Market Cap:* ${int(mc):,}\n"
        if volume: msg += f"📊 *Volume (1h):* ${int(volume):,}\n"
        if holders: msg += f"👥 *Holders:* {holders}\n"
        if launch_str: msg += launch_str
        msg += "\n"
        msg += "🛡️ *Security Check (RugCheck)*\n"
        msg += f"- {'✅' if lp_locked else '❌'} Liquidity Burned\n"
        msg += f"- {'✅' if freeze_removed else '❌'} Freeze Authority Removed\n"
        msg += f"- {'✅' if mint_revoked else '❌'} Mint Authority Revoked\n"
        msg += f"- {'🔒' if lp_locked else '🔓'} LP Locked\n"
        if rugscore is not None: msg += f"- 🔥 *RugScore:* {rugscore}/100\n"
        if risk_label: msg += f"- 🏷️ *RugCheck Label:* {risk_label}\n"
        if honeypot is not None: msg += f"- {'❌' if honeypot else '✅'} Honeypot: {'Yes' if honeypot else 'No'}\n"
        msg += attention
        msg += "\n"
        if top_holders:
            msg += "📊 *Top Holders:*\n"
            msg += "\n".join([f"{i+1}. {pct}%" for i, pct in enumerate(top_holders)])
            msg += "\n"
        msg += "\n"
        if symbol:
            msg += f"🔎 *Check X:* [Recherche X ${symbol}](https://twitter.com/search?q=%24{symbol}&src=typed_query)\n\n"
        msg += "📍 *Liens Utiles:*\n"
        msg += f"- 🌐 Pump.fun: pump.fun/{token_address}\n"
        msg += "\n"
        if token_address:
            msg += "🧬 *Adresse du Token:*\n"
            msg += f"`{token_address}`\n"

        # PATCH TRACKING ENRICHIT
        tracking[token_address] = {
            "symbol": symbol,
            "name": name,
            "initial": mc,
            "current": mc,
            "volume": volume,
            "holders": holders,
            "rugscore": rugscore,
            "bonding": get_bonding_curve(token_address),
            "top_holders": top_holders,
            "scamr": get_scamr_holders(token_address),
            "alerts": [],
            "timestamp": now
        }

        send_telegram_message(msg, token_address)
        save_for_analysis(token_address)
        logging.info(f"✅ Telegram message sent for token: {symbol}")

    # SAUVEGARDE LOCALE
    save_json(memory, MEMORY_FILE)
    save_json(tracking, TRACKING_FILE)
    save_json(wallet_stats, WALLET_STATS_FILE)

    # ENVOI À L'API TENDY (UNE SEULE FOIS!)
    tokens_list = []
    for token_address, track in tracking.items():
        tokens_list.append({
            "token_address": token_address,
            "symbol": track.get("symbol"),
            "initial": track.get("initial"),
            "current": track.get("current"),
            "alerts": track.get("alerts"),
            "timestamp": track.get("timestamp")
        })

    try:
        with open("analyses_history.json", "r", encoding="utf-8") as f:
            analyses_dict = json.load(f)
    except Exception:
        analyses_dict = {}

    send_to_tendy_api(tokens_list, analyses_dict)
    

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
        volume = token_data.get('volume') or 'N/A'
        holders = token_data.get('holders') or 'N/A'
        bonding_percent = token_data.get('bonding') or get_bonding_curve(token_address)
        rugscore = token_data.get('rugscore') or get_rugcheck_data(token_address)[0]
        top_list = token_data.get('top_holders') or get_top_holders(token_address)
        scamr_note = token_data.get('scamr') or get_scamr_holders(token_address)
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
        bonding_percent = get_bonding_curve(token_address)
        rugscore = get_rugcheck_data(token_address)[0]
        top_list = get_top_holders(token_address)
        scamr_note = get_scamr_holders(token_address)

    rugcheck_result = get_rugcheck_data(token_address)
    lp_locked = rugcheck_result[2] if rugcheck_result and len(rugcheck_result) > 2 else False
    holders_rug = rugcheck_result[3] if rugcheck_result and len(rugcheck_result) > 3 else None
    lp_status = "Locked" if lp_locked else "Not locked"
    smart_wallets = "Oui" if holders_rug and holders_rug > 100 else "Non"
    mentions = search_twitter_mentions(symbol)
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
