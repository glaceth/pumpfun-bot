print("🚀 Flask bot starting... loading routes...")

from flask import Flask, request

app = Flask(__name__)
ADMIN_USER_ID = "dummy"  # temporaire pour test

@app.route("/bot", methods=["POST"])
def receive_update():
    print("✅ /bot route registered")
    data = request.get_json()
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text = message.get("text", "")

    print("📨 Message reçu:", text)
    print("👤 Chat ID:", chat_id)

    if chat_id != ADMIN_USER_ID:
        print("❌ Unauthorized access")
        return "Unauthorized", 403

    if text == "/scan":
        print("✅ Scan lancé")
    elif text == "/status":
        print("📊 Status demandé")
    elif text == "/help":
        print("🆘 Help demandé")

    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
