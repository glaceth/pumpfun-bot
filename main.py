
import os
import time
import json
import requests
import openai
from datetime import datetime
from flask import Flask, request
from threading import Thread

app = Flask(__name__)
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY

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

def build_token_analysis_prompt(data):
    return f"""You are an experienced crypto trader with 20 years of market knowledge.

Here’s the data of a token just launched on Pump.fun:
- Name: {data['name']}
- Symbol: ${data['symbol']}
- Market Cap: ${data['market_cap']:,}
- Liquidity: ${data['liquidity']:,}
- Holders: {data['holders']}
- Bonding Curve: {data['bonding_percent']}%
- Rugscore: {data['rugscore']}
- Smart Wallet Detected: {'Yes' if data['smart_wallet'] else 'No'}
- Last Token Deployed by this wallet: {data['prev_token']} (${data['prev_mc']})
- Total Launches by Deployer: {data['launch_count']}

Please analyze this token from a risk/reward perspective.
Answer like a pro trader:
- Entry point advice
- Stop-loss suggestion
- What % of portfolio to allocate
- Take profit strategy
- Timeframe for re-evaluation
- Risk level (Low/Med/High) and brief reasoning"""

def ask_gpt(prompt):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a seasoned crypto trader providing risk-based analysis of meme tokens."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,
            temperature=0.7
        )
        return response.choices[0].message["content"]
    except Exception as e:
        return f"❌ GPT error: {str(e)}"
