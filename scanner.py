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


def fetch_24h_tickers():
    url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def score_candidate(t):
    pct = safe_float(t.get("priceChangePercent"))
    trades = safe_float(t.get("count"))
    qvol = safe_float(t.get("quoteVolume"))

    volume_score = math.log10(qvol + 1)
    trade_score = math.log10(trades + 1)

    # Prefer early movers, not already-pumped coins
    early_move_score = max(0, 6 - pct)

    score = volume_score + trade_score + early_move_score
    return score


def format_watchlist(candidates):
    lines = []
    lines.append("🟡 Early-move Watch (v2)")
    lines.append("Cleaner candidates only\n")

    for i, t in enumerate(candidates, start=1):
        symbol = t["symbol"].replace("USDT", "/USDT")
        pct = safe_float(t.get("priceChangePercent"))
        qvol = safe_float(t.get("quoteVolume")) / 1_000_000
        trades = int(safe_float(t.get("count")))

        lines.append(
            f"{i}) {symbol} | 24h: {pct:+.1f}% | Vol: ${qvol:.1f}M | Trades: {trades:,}"
        )

    lines.append("\nWatchlist only. Not a buy signal.")
    return "\n".join(lines)


def main():
    tickers = fetch_24h_tickers()

    excluded = ["BTCUSDT", "ETHUSDT", "USDCUSDT", "BUSDUSDT", "FDUSDUSDT", "TUSDUSDT"]

    candidates = []

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

        # Early-move filter
        if pct < 1 or pct > 6:
            continue

        # Liquidity filter
        if qvol < 10_000_000:
            continue

        # Activity filter
        if trades < 10_000:
            continue

        t["score"] = score_candidate(t)
        candidates.append(t)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    best = candidates[:5]

    if not best:
        tg_send("🟡 Early-move Watch (v2)\nNo clean early-move candidates right now.")
        return

    tg_send(format_watchlist(best))


if __name__ == "__main__":
    main()
