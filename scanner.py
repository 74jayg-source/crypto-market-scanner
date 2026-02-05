import os
import time
import math
import requests
from typing import List, Dict, Any, Tuple

BINANCE_BASE = "https://data-api.binance.vision"



def tg_send(text: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = requests.post(url, data={"chat_id": chat_id, "text": text}, timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f"Telegram send failed: {r.status_code} {r.text}")


def fetch_24h_tickers() -> List[Dict[str, Any]]:
    url = f"{BINANCE_BASE}/api/v3/ticker/24hr"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


def is_usdt_spot_symbol(sym: str) -> bool:
    # Binance spot symbols like "BTCUSDT". We only want USDT quoted pairs.
    # Exclude leveraged tokens and oddballs to reduce noise.
    if not sym.endswith("USDT"):
        return False
    banned_fragments = ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"]
    if any(sym.endswith(x) for x in banned_fragments):
        return False
    return True


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def score_candidate(t: Dict[str, Any]) -> Tuple[float, Dict[str, float]]:
    """
    Capital-first scoring:
    - Prefer meaningful liquidity: quoteVolume already handled by top-200 filter.
    - Prefer rising activity: count of trades is a proxy.
    - Prefer early momentum: % change positive but not already huge.
    - Penalize already-pumped moves (chasing).
    """
    last_price = safe_float(t.get("lastPrice"))
    pct = safe_float(t.get("priceChangePercent"))
    trades = safe_float(t.get("count"))  # number of trades in last 24h
    qvol = safe_float(t.get("quoteVolume"))

    # Normalize components (soft, log-based)
    trades_score = math.log10(trades + 1.0)  # 0.. ~6
    qvol_score = math.log10(qvol + 1.0)     # 0.. big

    # Momentum: reward 1%..8%, neutral at 0, penalize >15% (already pumped)
    if pct <= 0:
        momentum = -0.5
    elif pct <= 8:
        momentum = pct / 8.0                 # 0..1
    elif pct <= 15:
        momentum = 1.0 - (pct - 8) / 14.0    # gently down
    else:
        momentum = -0.3 - min((pct - 15) / 30.0, 0.7)  # strong penalty

    # Small penalty for extremely tiny price (often meme noise) — mild.
    tiny_price_penalty = 0.0
    if last_price > 0 and last_price < 0.00001:
        tiny_price_penalty = 0.2

    # Weighted sum: liquidity + activity + early momentum
    score = (0.35 * qvol_score) + (0.35 * trades_score) + (0.9 * momentum) - tiny_price_penalty

    details = {
        "pct": pct,
        "qvol": qvol,
        "trades": trades,
        "momentum": momentum,
        "qvol_score": qvol_score,
        "trades_score": trades_score,
        "tiny_penalty": tiny_price_penalty,
        "score": score,
    }
    return score, details


def format_watchlist(rows: List[Tuple[str, Dict[str, float]]]) -> str:
    lines = []
    lines.append("🟡 Big-move Watch (v1)")
    lines.append("Top candidates (capital-first filter)\n")

    for i, (sym, d) in enumerate(rows, start=1):
        pair = sym.replace("USDT", "/USDT")
        pct = d["pct"]
        qvol_m = d["qvol"] / 1_000_000.0
        trades = int(d["trades"])
        lines.append(
            f"{i}) {pair} | 24h: {pct:+.1f}% | Vol: ${qvol_m:.1f}M | Trades: {trades:,}"
        )

    lines.append("\nNote: This is a watchlist, not a signal. Always manage risk.")
    return "\n".join(lines)


def main() -> None:
    tickers = fetch_24h_tickers()

    # Filter to USDT spot-like symbols
    usdt = [t for t in tickers if is_usdt_spot_symbol(t.get("symbol", ""))]

    # Rank by quote volume and keep Top 200
    usdt.sort(key=lambda x: safe_float(x.get("quoteVolume")), reverse=True)
    top = usdt[:200]

    # Apply basic “capital-first” filters:
    # - Minimum 24h quote volume (avoid illiquid)
    # - Minimum trades (avoid dead pairs)
    MIN_QVOL = 5_000_000.0   # $5M
    MIN_TRADES = 5_000       # 5k trades/day

    candidates = []
    for t in top:
        qvol = safe_float(t.get("quoteVolume"))
        trades = safe_float(t.get("count"))
        if qvol < MIN_QVOL:
            continue
        if trades < MIN_TRADES:
            continue

        score, details = score_candidate(t)
        candidates.append((t["symbol"], score, details))

    # Sort by score and take top 5
    candidates.sort(key=lambda x: x[1], reverse=True)
    best = [(sym, details) for sym, _, details in candidates[:5]]

    if not best:
        tg_send("🟡 Big-move Watch (v1)\nNo candidates passed filters this run.")
        return

    msg = format_watchlist(best)
    tg_send(msg)


if __name__ == "__main__":
    main()
