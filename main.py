import os
from flask import Flask, request

app = Flask(__name__)

# Chargement sécurisé du token depuis les secrets Render
TELEGRAM_TOKEN = open("/etc/secrets/TELEGRAM_TOKEN").read().strip()

@app.route(f"/bot/{TELEGRAM_TOKEN}", methods=["POST"])
def receive_update():
    data = request.get_json()
    print("✅ /bot route registered")
    return "OK"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
