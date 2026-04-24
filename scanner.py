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
        "limit": 24
    })


def has_15m_acceleration(symbol):
    try:
        candles = fetch_15m_klines(symbol)
    except Exception:
        return False, "15m data failed"

    if len(candles) < 12:
        return False, "not enough candles"

    closes = [safe_float(c[4]) for c in candles]
    volumes = [safe_float(c[5]) for c in candles]

    last_close = closes[-1]
    close_1h_ago = closes[-5]
    close_3h_ago = closes[-13]

    move_1h = ((last_close - close_1h_ago) / close_1h_ago) * 100
    move_3h = ((last_close - close_3h_ago) / close_3h_ago) * 100

    recent_vol = sum(volumes[-4:]) / 4
    prior_vol = sum(volumes[-12:-4]) / 8

    if prior_vol <= 0:
        return False, "bad volume"

    vol_ratio = recent_vol / prior_vol

    # Pre-breakout / early acceleration rules
    if move_1h < 0.3:
        return False, f"1h weak {move_1h:.1f}%"

    if move_1h > 4.0:
        return False, f"1h too hot {move_1h:.1f}%"

    if move_3h > 8.0:
        return False, f"3h too extended {move_3h:.1f}%"

    if vol_ratio < 1.4:
        return False, f"volume not rising {vol_ratio:.1f}x"

    reason = f"15m acceleration: 1h {move_1h:+.1f}%, 3h {move_3h:+.1f}%, vol {vol_ratio:.1f}x"
    return True, reason


def score_candidate(t, reason):
    pct = safe_float(t.get("priceChangePercent"))
    trades = safe_float(t.get("count"))
    qvol = safe_float(t.get("quoteVolume"))

    volume_score = math.log10(qvol + 1)
    trade_score = math.log10(trades + 1)
    early_score = max(0, 6 - pct)

    return volume_score + trade_score + early_score


def format_watchlist(candidates):
    lines = []
    lines.append("⚡ Pre-breakout Watch (v3)")
    lines.append("24h early mover + 15m acceleration\n")

    for i, item in enumerate(candidates, start=1):
        t = item["ticker"]
        symbol = t["symbol"].replace("USDT", "/USDT")
        pct = safe_float(t.get("priceChangePercent"))
        qvol = safe_float(t.get("quoteVolume")) / 1_000_000
        trades = int(safe_float(t.get("count")))
        reason = item["reason"]

        lines.append(
            f"{i}) {symbol} | 24h: {pct:+.1f}% | Vol: ${qvol:.1f}M | Trades: {trades:,}\n   {reason}"
        )

    lines.append("\nWatchlist only. Not a buy signal.")
    return "\n".join(lines)


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

        # 24h early-move filter
        if pct < 1 or pct > 6:
            continue

        if qvol < 10_000_000:
            continue

        if trades < 10_000:
            continue

        first_pass.append(t)

    # Only check top 40 to keep GitHub run fast
    first_pass.sort(key=lambda x: safe_float(x.get("quoteVolume")), reverse=True)
    first_pass = first_pass[:40]

    candidates = []

    for t in first_pass:
        symbol = t["symbol"]
        ok, reason = has_15m_acceleration(symbol)

        if not ok:
            continue

        score = score_candidate(t, reason)

        candidates.append({
            "ticker": t,
            "score": score,
            "reason": reason
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[:5]

    if not best:
        tg_send("⚡ Pre-breakout Watch (v3)\nNo clean 15m acceleration setups right now.")
        return

    tg_send(format_watchlist(best))


if __name__ == "__main__":
    main()
