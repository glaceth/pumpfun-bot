import os
import time
import json
import requests
from flask import Flask, request
from threading import Thread

# === Secrets ===
with open("/etc/secrets/TELEGRAM_TOKEN") as f:
    TELEGRAM_TOKEN = f.read().strip()
with open("/etc/secrets/ADMIN_USER_ID") as f:
    ADMIN_USER_ID = f.read().strip()

# === Flask App ===
app = Flask(__name__)

# === Mock functions (replace with real ones in full version) ===
def send_telegram_message(message, token_address):
    print(f"[MOCK] Sending Telegram message:")
{message}")

def load_json(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def check_tokens():
    print("[MOCK] Token scanning triggered manually.")

# === Constants for testing ===
MEMORY_FILE = "memory.json"
TRACKING_FILE = "tracking.json"

# === Main Webhook Route ===
@app.route(f"/bot/{TELEGRAM_TOKEN}", methods=["POST"])
def receive_update():
    data = request.get_json()
    print("✅ /bot route triggered")

    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "")

    if chat_id != ADMIN_USER_ID:
        print("⛔ Unauthorized access attempt")
        return "Unauthorized", 403

    if text == "/scan":
        send_telegram_message("✅ Scan manuel lancé...", "manual")
        check_tokens()

    elif text == "/status":
        try:
            memory = load_json(MEMORY_FILE)
            tracking = load_json(TRACKING_FILE)
            tokens_today = [k for k, v in memory.items() if time.time() - v < 86400]
            alerts = len(tracking)
            msg = f"📊 *Status du bot Pump.fun*\n\n- 🔍 Tokens scannés aujourd'hui : {len(tokens_today)}\n- 🚀 Tokens envoyés depuis lancement : {alerts}"
        except:
            msg = "❌ Erreur lors de la récupération du status."
        send_telegram_message(msg, "manual")

    elif text == "/help":
        msg = (
            "🤖 *Commandes disponibles*\n"
            "• `/scan` – Lancer un scan manuel maintenant\n"
            "• `/status` – Voir combien de tokens ont été scannés et envoyés\n"
            "• `/help` – Afficher cette aide"
        )
        send_telegram_message(msg, "manual")

    return "OK"

# === Launch Flask App ===
def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    Thread(target=run_flask).start()
    while True:
        time.sleep(60)
