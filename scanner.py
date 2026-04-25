import os
import math
import requests

BINANCE_BASE = "https://data-api.binance.vision"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg}, timeout=20)
    r.raise_for_status()


def safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default


def get_json(path, params=None):
    r = requests.get(f"{BINANCE_BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_24h_tickers():
    return get_json("/api/v3/ticker/24hr")


def fetch_15m_klines(symbol):
    return get_json("/api/v3/klines", {
        "symbol": symbol,
        "interval": "15m",
        "limit": 40
    })


def fmt_price(x):
    if x >= 1:
        return f"{x:.4f}"
    if x >= 0.01:
        return f"{x:.5f}"
    return f"{x:.8f}"


def analyse_structure(symbol):
    try:
        candles = fetch_15m_klines(symbol)
    except Exception:
        return None

    if not isinstance(candles, list) or len(candles) < 30:
        return None

    highs = [safe_float(c[2]) for c in candles]
    lows = [safe_float(c[3]) for c in candles]
    closes = [safe_float(c[4]) for c in candles]
    volumes = [safe_float(c[5]) for c in candles]

    last = closes[-1]
    close_1h_ago = closes[-5]
    close_3h_ago = closes[-13]

    move_1h = ((last - close_1h_ago) / close_1h_ago) * 100
    move_3h = ((last - close_3h_ago) / close_3h_ago) * 100

    recent_vol = sum(volumes[-4:]) / 4
    prior_vol = sum(volumes[-16:-4]) / 12
    vol_ratio = recent_vol / prior_vol if prior_vol > 0 else 0

    recent_range = max(highs[-8:]) - min(lows[-8:])
    prior_range = max(highs[-24:-8]) - min(lows[-24:-8])
    compression_ratio = recent_range / prior_range if prior_range > 0 else 1

    recent_high = max(highs[-12:])
    recent_low = min(lows[-12:])

    distance_from_high = ((recent_high - last) / recent_high) * 100
    bounce_from_low = ((last - recent_low) / recent_low) * 100

    # Freshness / structure checks
    near_high = distance_from_high <= 1.8
    not_dumping = move_1h >= 0.2
    not_overheated = move_1h <= 5.5 and move_3h <= 12
    volume_rising = vol_ratio >= 1.25
    some_compression = compression_ratio <= 0.95

    passed = (
        near_high
        and not_dumping
        and not_overheated
        and volume_rising
        and some_compression
    )

    return {
        "passed": passed,
        "last": last,
        "move_1h": move_1h,
        "move_3h": move_3h,
        "vol_ratio": vol_ratio,
        "compression_ratio": compression_ratio,
        "distance_from_high": distance_from_high,
        "bounce_from_low": bounce_from_low,
        "recent_high": recent_high,
        "recent_low": recent_low
    }


def score_candidate(t, s):
    pct = safe_float(t.get("priceChangePercent"))
    qvol = safe_float(t.get("quoteVolume"))
    trades = safe_float(t.get("count"))

    score = 0

    # Daily gainer sweet spot
    if 2 <= pct <= 6:
        score += 8
    elif 1 <= pct < 2:
        score += 5
    elif 6 < pct <= 10:
        score += 3

    # Liquidity / activity
    score += min(math.log10(qvol + 1), 10)
    score += min(math.log10(trades + 1), 7)

    # Structure / freshness
    score += max(0, (1.8 - s["distance_from_high"]) * 3)
    score += max(0, (1.0 - s["compression_ratio"]) * 8)
    score += min(s["vol_ratio"] * 2, 10)
    score += min(s["move_1h"] * 2, 8)

    return score


def price_plan(price):
    entry_low = price * 0.995
    entry_high = price * 1.005
    stop = price * 0.96

    t1 = price * 1.10
    t2 = price * 1.20
    t3 = price * 1.30

    return entry_low, entry_high, stop, t1, t2, t3


def build_alert(c):
    t = c["ticker"]
    s = c["structure"]

    symbol = t["symbol"].replace("USDT", "/USDT")
    price = safe_float(t.get("lastPrice"))
    pct = safe_float(t.get("priceChangePercent"))
    qvol = safe_float(t.get("quoteVolume")) / 1_000_000
    trades = int(safe_float(t.get("count")))

    entry_low, entry_high, stop, t1, t2, t3 = price_plan(price)

    return (
        "🏁 V8 MUSCLE — BEST Daily Riser Candidate\n\n"
        f"{symbol}\n"
        f"Current: {fmt_price(price)}\n"
        f"24h: {pct:+.1f}%\n"
        f"Volume: ${qvol:.1f}M\n"
        f"Trades: {trades:,}\n\n"
        "WHY THIS ONE\n"
        f"15m/1h momentum: {s['move_1h']:+.1f}%\n"
        f"3h move: {s['move_3h']:+.1f}%\n"
        f"Volume expansion: {s['vol_ratio']:.1f}x\n"
        f"Compression: {s['compression_ratio']:.2f}\n"
        f"Near recent high: {s['distance_from_high']:.1f}% away\n\n"
        "PLAN\n"
        f"Entry zone: {fmt_price(entry_low)} – {fmt_price(entry_high)}\n"
        f"Stop / invalidation: below {fmt_price(stop)}\n\n"
        f"Target 1: {fmt_price(t1)} (+10%)\n"
        f"Target 2: {fmt_price(t2)} (+20%)\n"
        f"Stretch: {fmt_price(t3)} (+30%)\n\n"
        "Management idea: take some profit at T1, protect the rest.\n"
        "Watchlist only. Not financial advice."
    )


def main():
    data = fetch_24h_tickers()

    if not isinstance(data, list):
        send_telegram("⚠️ Binance API issue. Skipping this run.")
        return

    excluded = {
        "BTCUSDT", "ETHUSDT", "USDCUSDT", "BUSDUSDT",
        "FDUSDUSDT", "TUSDUSDT", "DAIUSDT"
    }

    first_pass = []

    for t in data:
        symbol = t.get("symbol", "")
        pct = safe_float(t.get("priceChangePercent"))
        qvol = safe_float(t.get("quoteVolume"))
        trades = safe_float(t.get("count"))

        if not symbol.endswith("USDT"):
            continue

        if symbol in excluded:
            continue

        if any(x in symbol for x in ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"]):
            continue

        # Catch before daily riser, not after
        if pct < 1 or pct > 10:
            continue

        if qvol < 10_000_000:
            continue

        if trades < 50_000:
            continue

        first_pass.append(t)

    first_pass.sort(key=lambda x: safe_float(x.get("quoteVolume")), reverse=True)
    first_pass = first_pass[:60]

    candidates = []

    for t in first_pass:
        symbol = t["symbol"]
        structure = analyse_structure(symbol)

        if not structure:
            continue

        if not structure["passed"]:
            continue

        score = score_candidate(t, structure)

        candidates.append({
            "ticker": t,
            "structure": structure,
            "score": score
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    if not candidates:
        send_telegram("🏁 V8 MUSCLE\nNo clean daily-riser setup right now.")
        return

    best = candidates[0]
    send_telegram(build_alert(best))


if __name__ == "__main__":
    main()
