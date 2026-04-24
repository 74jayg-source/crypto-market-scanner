import os
import math
import requests

BINANCE_BASE = "https://data-api.binance.vision"


def tg_send(text):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=20)
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
        "limit": 32
    })


# 🔥 NEW: Compression detection
def is_compressing(closes):
    recent = closes[-8:]     # last 2 hours
    earlier = closes[-24:-8] # prior 4 hours

    if len(earlier) < 8:
        return False

    recent_range = max(recent) - min(recent)
    earlier_range = max(earlier) - min(earlier)

    if earlier_range == 0:
        return False

    compression_ratio = recent_range / earlier_range

    # smaller range = compression
    return compression_ratio < 0.6


def has_15m_acceleration(symbol):
    try:
        candles = fetch_15m_klines(symbol)
    except Exception:
        return False, "15m data failed", None

    if len(candles) < 24:
        return False, "not enough candles", None

    closes = [safe_float(c[4]) for c in candles]
    volumes = [safe_float(c[5]) for c in candles]

    last_close = closes[-1]
    close_1h_ago = closes[-5]
    close_3h_ago = closes[-13]

    move_1h = ((last_close - close_1h_ago) / close_1h_ago) * 100
    move_3h = ((last_close - close_3h_ago) / close_3h_ago) * 100

    recent_vol = sum(volumes[-4:]) / 4
    prior_vol = sum(volumes[-16:-4]) / 12

    if prior_vol <= 0:
        return False, "bad volume", None

    vol_ratio = recent_vol / prior_vol

    # 🔥 NEW: compression check
    compressing = is_compressing(closes)

    if not compressing:
        return False, "no compression", None

    if move_1h < 0.3:
        return False, f"1h weak {move_1h:.1f}%", None

    if move_1h > 5.0:
        return False, f"1h too hot {move_1h:.1f}%", None

    if move_3h > 10.0:
        return False, f"3h too extended {move_3h:.1f}%", None

    if vol_ratio < 1.4:
        return False, f"volume not rising {vol_ratio:.1f}x", None

    reason = f"Compression + breakout: 1h {move_1h:+.1f}%, vol {vol_ratio:.1f}x"

    data = {
        "last_close": last_close,
        "vol_ratio": vol_ratio
    }

    return True, reason, data


def score_candidate(t, accel_data):
    pct = safe_float(t.get("priceChangePercent"))
    trades = safe_float(t.get("count"))
    qvol = safe_float(t.get("quoteVolume"))

    volume_score = math.log10(qvol + 1)
    trade_score = math.log10(trades + 1)
    early_score = max(0, 6 - pct)
    accel_score = accel_data["vol_ratio"] * 2

    return volume_score + trade_score + early_score + accel_score


def price_plan(price):
    entry_low = price * 0.995
    entry_high = price * 1.005

    stop = price * 0.96

    t1 = price * 1.10
    t2 = price * 1.20
    t3 = price * 1.30

    return entry_low, entry_high, stop, t1, t2, t3


def fmt_price(x):
    if x >= 1:
        return f"{x:.4f}"
    elif x >= 0.01:
        return f"{x:.5f}"
    else:
        return f"{x:.8f}"


def format_watchlist(candidates):
    item = candidates[0]
    t = item["ticker"]

    symbol = t["symbol"].replace("USDT", "/USDT")
    pct = safe_float(t.get("priceChangePercent"))
    qvol = safe_float(t.get("quoteVolume")) / 1_000_000
    trades = int(safe_float(t.get("count")))
    reason = item["reason"]

    price = safe_float(t.get("lastPrice"))
    entry_low, entry_high, stop, t1, t2, t3 = price_plan(price)

    return (
        "🚀 BEST Pre-breakout Setup (v5)\n\n"
        f"{symbol}\n"
        f"Current: {fmt_price(price)}\n"
        f"24h: {pct:+.1f}%\n"
        f"Volume: ${qvol:.1f}M\n"
        f"Trades: {trades:,}\n\n"
        f"{reason}\n\n"
        "PLAN\n"
        f"Entry: {fmt_price(entry_low)} – {fmt_price(entry_high)}\n"
        f"Stop: below {fmt_price(stop)}\n\n"
        f"T1: {fmt_price(t1)} (+10%)\n"
        f"T2: {fmt_price(t2)} (+20%)\n"
        f"T3: {fmt_price(t3)} (+30%)\n"
    )


def main():
    tickers = fetch_24h_tickers()

    excluded = [
        "BTCUSDT", "ETHUSDT", "USDCUSDT", "BUSDUSDT",
        "FDUSDUSDT", "TUSDUSDT", "DAIUSDT"
    ]

    first_pass = []

    for t in tickers:
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

        if pct < 1 or pct > 6:
            continue

        if qvol < 10_000_000:
            continue

        if trades < 10_000:
            continue

        first_pass.append(t)

    first_pass.sort(key=lambda x: safe_float(x.get("quoteVolume")), reverse=True)
    first_pass = first_pass[:40]

    candidates = []

    for t in first_pass:
        symbol = t["symbol"]
        ok, reason, accel_data = has_15m_acceleration(symbol)

        if not ok:
            continue

        score = score_candidate(t, accel_data)

        candidates.append({
            "ticker": t,
            "score": score,
            "reason": reason
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[:1]

    if not best:
        tg_send("🚀 Pre-breakout Watch (v5)\nNo compression + breakout setups right now.")
        return

    tg_send(format_watchlist(best))


if __name__ == "__main__":
    main()
