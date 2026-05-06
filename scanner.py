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


def get_aud_rate():
    try:
        r = requests.get("https://api.exchangerate-api.com/v4/latest/USD", timeout=10)
        data = r.json()
        return safe_float(data["rates"]["AUD"], 1.5)
    except Exception:
        return 1.5


def fetch_24h_tickers():
    return get_json("/api/v3/ticker/24hr")


def fetch_klines(symbol, interval, limit):
    return get_json("/api/v3/klines", {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    })


def fmt_price(x):
    if x >= 1:
        return f"{x:.4f}"
    if x >= 0.01:
        return f"{x:.5f}"
    return f"{x:.8f}"


def analyse_daily(symbol):
    try:
        candles = fetch_klines(symbol, "1d", 35)
    except Exception:
        return None

    if not isinstance(candles, list) or len(candles) < 25:
        return None

    current = candles[-1]
    previous = candles[:-1]

    today_open = safe_float(current[1])
    today_high = safe_float(current[2])
    today_low = safe_float(current[3])
    today_close = safe_float(current[4])
    today_quote_vol = safe_float(current[7])

    last_10 = previous[-10:]
    last_20 = previous[-20:]

    prev_10_high = max(safe_float(c[2]) for c in last_10)
    prev_10_low = min(safe_float(c[3]) for c in last_10)

    prev_20_high = max(safe_float(c[2]) for c in last_20)
    prev_20_low = min(safe_float(c[3]) for c in last_20)

    avg_10_quote_vol = sum(safe_float(c[7]) for c in last_10) / len(last_10)

    if today_open <= 0 or prev_10_low <= 0 or prev_20_low <= 0 or avg_10_quote_vol <= 0:
        return None

    daily_move = ((today_close - today_open) / today_open) * 100
    base_range_10 = ((prev_10_high - prev_10_low) / prev_10_low) * 100
    base_range_20 = ((prev_20_high - prev_20_low) / prev_20_low) * 100

    breakout_10 = ((today_close - prev_10_high) / prev_10_high) * 100
    breakout_20 = ((today_close - prev_20_high) / prev_20_high) * 100

    vol_ratio = today_quote_vol / avg_10_quote_vol

    near_daily_breakout = today_close >= prev_10_high * 0.985
    not_too_late = daily_move <= 24
    volume_alive = vol_ratio >= 0.6

    passed = near_daily_breakout and not_too_late and volume_alive

    return {
        "passed": passed,
        "today_open": today_open,
        "today_close": today_close,
        "today_high": today_high,
        "today_low": today_low,
        "prev_10_high": prev_10_high,
        "prev_20_high": prev_20_high,
        "daily_move": daily_move,
        "base_range_10": base_range_10,
        "base_range_20": base_range_20,
        "breakout_10": breakout_10,
        "breakout_20": breakout_20,
        "vol_ratio": vol_ratio
    }


def analyse_1h(symbol):
    try:
        candles = fetch_klines(symbol, "1h", 24)
    except Exception:
        return None

    if not isinstance(candles, list) or len(candles) < 12:
        return None

    highs = [safe_float(c[2]) for c in candles]
    lows = [safe_float(c[3]) for c in candles]
    closes = [safe_float(c[4]) for c in candles]
    volumes = [safe_float(c[7]) for c in candles]

    last = closes[-1]
    close_1h_ago = closes[-2]
    close_4h_ago = closes[-5]
    close_8h_ago = closes[-9]

    move_1h = ((last - close_1h_ago) / close_1h_ago) * 100
    move_4h = ((last - close_4h_ago) / close_4h_ago) * 100
    move_8h = ((last - close_8h_ago) / close_8h_ago) * 100

    recent_high = max(highs[-8:])
    recent_low = min(lows[-8:])

    distance_from_high = ((recent_high - last) / recent_high) * 100
    bounce_from_low = ((last - recent_low) / recent_low) * 100

    recent_vol = sum(volumes[-3:]) / 3
    prior_vol = sum(volumes[-12:-3]) / 9
    hourly_vol_ratio = recent_vol / prior_vol if prior_vol > 0 else 0

    # anti-chop / confirmation
    passed = (
        move_4h >= 0.3
        and move_8h >= 0.4
        and distance_from_high <= 5.5
        and hourly_vol_ratio >= 0.7
    )

    return {
        "passed": passed,
        "move_1h": move_1h,
        "move_4h": move_4h,
        "move_8h": move_8h,
        "distance_from_high": distance_from_high,
        "bounce_from_low": bounce_from_low,
        "hourly_vol_ratio": hourly_vol_ratio
    }


def score_candidate(t, daily, hourly):
    pct = safe_float(t.get("priceChangePercent"))
    qvol = safe_float(t.get("quoteVolume"))
    trades = safe_float(t.get("count"))

    score = 0

    # 24h sweet spot
    if 3 <= pct <= 12:
        score += 18
    elif 1.5 <= pct < 3:
        score += 12
    elif 12 < pct <= 22:
        score += 7

    # daily breakout structure
    if daily["breakout_10"] >= 0:
        score += 18
    elif daily["breakout_10"] >= -1.5:
        score += 11

    if daily["breakout_20"] >= 0:
        score += 8
    elif daily["breakout_20"] >= -2:
        score += 4

    # base / compression on daily
    if daily["base_range_10"] <= 18:
        score += 12
    elif daily["base_range_10"] <= 30:
        score += 8
    elif daily["base_range_10"] <= 45:
        score += 4

    # volume
    score += min(daily["vol_ratio"] * 6, 14)
    score += min(hourly["hourly_vol_ratio"] * 5, 10)

    # hourly confirmation
    score += min(max(hourly["move_4h"], 0) * 2, 8)
    score += min(max(hourly["move_8h"], 0), 6)
    score += max(0, (5.5 - hourly["distance_from_high"]))

    # liquidity
    score += min(math.log10(qvol + 1), 10)
    score += min(math.log10(trades + 1), 7)

    # penalties
    if pct > 18:
        score -= 8
    if daily["daily_move"] > 20:
        score -= 8
    if hourly["distance_from_high"] > 4:
        score -= 5
    if daily["base_range_10"] > 50:
        score -= 7

    return max(0, min(round(score), 100))


def grade(score):
    if score >= 80:
        return "HIGH QUALITY"
    if score >= 65:
        return "DECENT WATCH"
    if score >= 50:
        return "WEAK / NEEDS CONFIRMATION"
    return "IGNORE / LOW QUALITY"


def price_plan(price):
    entry_low = price * 0.995
    entry_high = price * 1.005
    stop = price * 0.955

    t1 = price * 1.10
    t2 = price * 1.20
    t3 = price * 1.30

    return entry_low, entry_high, stop, t1, t2, t3


def build_alert(c, aud_rate):
    t = c["ticker"]
    d = c["daily"]
    h = c["hourly"]

    symbol = t["symbol"].replace("USDT", "/USDT")
    price = safe_float(t.get("lastPrice"))
    pct = safe_float(t.get("priceChangePercent"))
    qvol = safe_float(t.get("quoteVolume")) / 1_000_000
    trades = int(safe_float(t.get("count")))
    score = c["score"]

    entry_low, entry_high, stop, t1, t2, t3 = price_plan(price)

    return (
        "🏎️ V9 DAILY HUNTER — SCORED\n\n"
        f"{symbol}\n"
        f"Score: {score}/100 — {grade(score)}\n\n"
        f"Current: {fmt_price(price)} USDT / ${fmt_price(price * aud_rate)} AUD\n"
        f"24h: {pct:+.1f}%\n"
        f"Volume: ${qvol:.1f}M USDT\n"
        f"Trades: {trades:,}\n\n"
        "WHY THIS ONE\n"
        f"Daily move from open: {d['daily_move']:+.1f}%\n"
        f"Vs 10-day high: {d['breakout_10']:+.1f}%\n"
        f"Vs 20-day high: {d['breakout_20']:+.1f}%\n"
        f"10-day base range: {d['base_range_10']:.1f}%\n"
        f"Daily volume vs avg: {d['vol_ratio']:.1f}x\n"
        f"4h momentum: {h['move_4h']:+.1f}%\n"
        f"8h momentum: {h['move_8h']:+.1f}%\n"
        f"Near 1h high: {h['distance_from_high']:.1f}% away\n\n"
        "PLAN\n"
        f"Entry: {fmt_price(entry_low)} – {fmt_price(entry_high)} USDT\n"
        f"       ${fmt_price(entry_low * aud_rate)} – ${fmt_price(entry_high * aud_rate)} AUD\n"
        f"Stop: below {fmt_price(stop)} USDT / ${fmt_price(stop * aud_rate)} AUD\n\n"
        f"T1: {fmt_price(t1)} USDT / ${fmt_price(t1 * aud_rate)} AUD (+10%)\n"
        f"T2: {fmt_price(t2)} USDT / ${fmt_price(t2 * aud_rate)} AUD (+20%)\n"
        f"T3: {fmt_price(t3)} USDT / ${fmt_price(t3 * aud_rate)} AUD (+30%)\n\n"
        "Management idea: take some at T1, protect the rest.\n"
        "Watchlist only. Not financial advice."
    )


def main():
    aud_rate = get_aud_rate()
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

        if pct < 1.5 or pct > 22:
            continue

        if qvol < 3_000_000:
            continue

        if trades < 20_000:
            continue

        first_pass.append(t)

    first_pass.sort(key=lambda x: safe_float(x.get("quoteVolume")), reverse=True)
    first_pass = first_pass[:80]

    candidates = []

    for t in first_pass:
        symbol = t["symbol"]

        daily = analyse_daily(symbol)
        if not daily or not daily["passed"]:
            continue

        hourly = analyse_1h(symbol)
        if not hourly or not hourly["passed"]:
            continue

        score = score_candidate(t, daily, hourly)

        candidates.append({
            "ticker": t,
            "daily": daily,
            "hourly": hourly,
            "score": score
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)

    if not candidates:
        send_telegram("🏎️ V9 DAILY HUNTER\nNo clean daily breakout setup right now.")
        return

    best = candidates[0]
    send_telegram(build_alert(best, aud_rate))


if __name__ == "__main__":
    main()
