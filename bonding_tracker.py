
import requests
import json
import time
from datetime import datetime

API_URL = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/bonding"
HEADERS = {
    "accept": "application/json",
    "X-API-Key": "YOUR_API_KEY_HERE"
}
OUTPUT_FILE = "token_bonded_list.json"

def fetch_bonding_tokens():
    try:
        response = requests.get(API_URL, headers=HEADERS, params={"limit": 100})
        if response.status_code == 200:
            tokens = response.json().get("result", [])
            graduated = {t["tokenAddress"]: datetime.utcnow().isoformat() for t in tokens}
            with open(OUTPUT_FILE, "w") as f:
                json.dump(graduated, f)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⛓ Graduated tokens tracked: {len(graduated)}")
        else:
            print("❌ Failed to fetch bonding tokens")
    except Exception as e:
        print("Erreur bonding_tracker:", e)

if __name__ == "__main__":
    while True:
        fetch_bonding_tokens()
        time.sleep(60)
