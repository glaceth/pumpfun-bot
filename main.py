    }
    try:
        requests.post(url, json=payload)
        time.sleep(2)
    except Exception as e:
        print("❌ Erreur Telegram:", e)

def load_memory(file):
    if not os.path.exists(file):
        return {}
    with open(file, "r") as f:
        return json.load(f)

def save_memory(data, file):
    with open(file, "w") as f:
        json.dump(data, f)

def is_new_token(token_address, memory):
    return token_address not in memory

def check_tokens():
    print("🔍 Checking tokens...")
    try:
        response = requests.get(API_URL, headers=HEADERS)
        data = response.json().get("result", [])
    except Exception as e:
        print("❌ Erreur API Moralis:", e)
        return

    memory = load_memory(MEMORY_FILE)
    bonded_memory = load_memory(BONDED_FILE)
    now = time.time()

    for token in data:
        token_address = token.get("tokenAddress")
        if not token_address or not is_new_token(token_address, memory):
            continue

        name = token.get("name", "N/A")
        symbol = token.get("symbol", "N/A")
        mc = float(token.get("fullyDilutedValuation") or 0)
        lq = float(token.get("liquidity") or 0)
        mentions = token.get("mentions") or 0
        rugscore = token.get("rugscore") or 0
