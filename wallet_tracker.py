import json
import os

STATS_FILE = "wallet_stats.json"

def load_wallet_stats():
    if not os.path.exists(STATS_FILE):
        return {}
    with open(STATS_FILE, "r") as f:
        return json.load(f)

def save_wallet_stats(data):
    with open(STATS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def update_wallet_stats(wallet_address, is_win):
    stats = load_wallet_stats()
    if wallet_address not in stats:
        stats[wallet_address] = {"wins": 0, "total": 0}
    stats[wallet_address]["total"] += 1
    if is_win:
        stats[wallet_address]["wins"] += 1
    save_wallet_stats(stats)

def get_wallet_winrate(wallet_address):
    stats = load_wallet_stats()
    data = stats.get(wallet_address)
    if not data or data["total"] == 0:
        return None
    return round(100 * data["wins"] / data["total"], 1)
