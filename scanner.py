import requests
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})

def get_data():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    return requests.get(url).json()

def score_token(t):
    change = float(t["priceChangePercent"])
    volume = float(t["quoteVolume"])
    trades = int(t["count"])

    # Base filters
    if not t["symbol"].endswith("USDT"):
        return None

    if any(x in t["symbol"] for x in ["BTC", "ETH", "USDC", "BUSD"]):
        return None

    # -------- PATH A: CLEAN SETUP (v6 style) --------
    clean_score = 0

    if 1 <= change <= 6:
        clean_score += 2
    if volume > 10_000_000:
        clean_score += 2
    if trades > 100_000:
        clean_score += 1

    # -------- PATH B: MOMENTUM SPIKE (NEW) --------
    momentum_score = 0

    if 2 <= change <= 12:
        momentum_score += 2
    if volume > 20_000_000:
        momentum_score += 2
    if trades > 150_000:
        momentum_score += 1

    # Reject already blown out coins
    if change > 20:
        return None

    final_score = max(clean_score, momentum_score)

    if final_score < 3:
        return None

    return {
        "symbol": t["symbol"],
        "price": float(t["lastPrice"]),
        "change": change,
        "volume": volume,
        "trades": trades,
        "score": final_score
    }

def build_plan(t):
    price = t["price"]

    entry_low = price * 0.995
    entry_high = price * 1.005

    stop = price * 0.96

    t1 = price * 1.10
    t2 = price * 1.20
    t3 = price * 1.30

    return f"""🚀 BEST Daily Riser Candidate (v7)

{t['symbol']}
Current: {price:.4f}
24h: +{t['change']:.1f}%
Volume: ${t['volume']/1_000_000:.1f}M
Trades: {t['trades']:,}

PLAN
Entry: {entry_low:.4f} – {entry_high:.4f}
Stop: below {stop:.4f}

Target 1: {t1:.4f} (+10%)
Target 2: {t2:.4f} (+20%)
Stretch: {t3:.4f} (+30%)

Take profit at T1, protect the rest.
Watchlist only. Not financial advice.
"""

def main():
    data = get_data()

# safety check
if not isinstance(data, list):
    send_telegram("⚠️ Binance API error. Skipping run.")
    return
    
    candidates = []

    for t in data:
        scored = score_token(t)
        if scored:
            candidates.append(scored)

    if not candidates:
        send_telegram("🚫 No strong early movers right now.")
        return

    # pick BEST only
    best = sorted(candidates, key=lambda x: x["score"], reverse=True)[0]

    msg = build_plan(best)
    send_telegram(msg)

if __name__ == "__main__":
    main()
