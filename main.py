import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Chargement des variables d'environnement
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "Glacesol")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

def send_telegram_message(text, chat_id=None):
    if not chat_id:
        chat_id = CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print("❌ Failed to send Telegram message:", e)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"status": "ignored"})

    message = data["message"]
    chat_id = message["chat"]["id"]
    username = message["from"].get("username", "")
    text = message.get("text", "")

    if text == "/scan":
        if username != ADMIN_USER_ID:
            send_telegram_message("🚫 Unauthorized user", chat_id)
            return jsonify({"status": "unauthorized"})
        send_telegram_message("✅ Scan manuel lancé...", chat_id)
    elif text == "/help":
        send_telegram_message("📘 Commands available:\n/scan - Manual scan\n/help - This help message", chat_id)
    else:
        send_telegram_message("🤖 Unknown command. Try /help", chat_id)

    return jsonify({"status": "ok"})

if __name__ == "__main__":
    print("🚀 Flask bot starting... checking username based authorization...")
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
