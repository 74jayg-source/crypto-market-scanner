import requests
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})


def get_data():
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        r = requests.get(url, timeout=10)
        return r.json()
    except:
        return None


def score_token(t):
    try:
        symbol = t["symbol"]
        change = float(t["priceChangePercent"])
        volume = float(t["quoteVolume"])
        trades = int(t["count"])
        price = float(t["lastPrice"])
    except:
        return None

    # Only USDT pairs
    if not symbol.endswith("USDT"):
        return None

    # Remove majors/stables
    if any(x in symbol for x in ["BTC", "ETH", "USDC", "BUSD"]):
        return None

    # Ignore already pumped coins
    if change > 20:
        return None

    score = 0
    reason = ""

    # ----------------------------
    # PATH A: Early Clean Move
    # ----------------------------
    if 1 <= change <= 6:
        score += 2
        reason = "early trend"

    if volume > 10_000_000:
        score += 2

    if trades > 100_000:
        score += 1

    # ----------------------------
    # PATH B: Momentum Ignition
    # ----------------------------
    if 2 <= change <= 12:
        score += 2
        reason = "momentum ignition"

    if volume > 20_000_000:
        score += 2

    if trades > 150_000:
        score += 1

    # Must meet minimum quality
    if score < 4:
        return None

    return {
        "symbol": symbol,
        "price": price,
        "change": change,
        "volume": volume,
        "trades": trades,
        "score": score,
        "reason": reason
    }


def build_plan(t):
    price = t["price"]

    entry_low = price * 0.995
    entry_high = price * 1.005

    stop = price * 0.96

    t1 = price * 1.10
    t2 = price * 1.20
    t3 = price * 1.30

    return f"""🚀 BEST Early Gainer Setup (v7)

{t['symbol']}
Reason: {t['reason']}

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

    # API safety
    if not data or not isinstance(data, list):
        send_telegram("⚠️ Binance API issue. Skipping this run.")
        return

    candidates = []

    for t in data:
        result = score_token(t)
        if result:
            candidates.append(result)

    if not candidates:
        send_telegram("🚫 No strong early movers right now.")
        return

    # Pick best only
    best = sorted(candidates, key=lambda x: x["score"], reverse=True)[0]

    msg = build_plan(best)
    send_telegram(msg)


if __name__ == "__main__":
    main()
