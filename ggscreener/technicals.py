from __future__ import annotations

from collections import defaultdict
from datetime import date

from .utils import num, pct_change, ts_to_et


def sma(values: list[float], length: int) -> float | None:
    if len(values) < length:
        return None
    return sum(values[-length:]) / length


def ema(values: list[float], length: int) -> float | None:
    if len(values) < length:
        return None
    alpha = 2 / (length + 1)
    value = sum(values[:length]) / length
    for x in values[length:]:
        value = alpha * x + (1 - alpha) * value
    return value


def atr(bars: list[dict], length: int = 14) -> float | None:
    if len(bars) < length + 1:
        return None
    trs = []
    for prev, cur in zip(bars[:-1], bars[1:]):
        high = num(cur.get("h"))
        low = num(cur.get("l"))
        prev_close = num(prev.get("c"))
        if high is None or low is None or prev_close is None:
            continue
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    if len(trs) < length:
        return None
    return sum(trs[-length:]) / length


def completed_daily_bars(bars: list[dict], current_date: date) -> list[dict]:
    """Remove an in-progress current-day daily bar.

    Moving averages, prior highs/lows and ATR should be based on completed
    sessions. Current price is injected separately into trend decisions.
    """
    out = []
    for bar in bars:
        t = bar.get("t")
        if t is None:
            continue
        if ts_to_et(int(t)).date() < current_date:
            out.append(bar)
    return out


def daily_metrics(bars: list[dict]) -> dict:
    closes = [num(x.get("c")) for x in bars]
    closes = [x for x in closes if x is not None]
    if not closes:
        return {}
    historical_close = closes[-1]
    highs = [num(x.get("h")) for x in bars if num(x.get("h")) is not None]
    lows = [num(x.get("l")) for x in bars if num(x.get("l")) is not None]
    prior20 = bars[-20:] if len(bars) >= 20 else bars
    prior20_high = max((num(x.get("h"), float("-inf")) for x in prior20), default=None)
    prior20_low = min((num(x.get("l"), float("inf")) for x in prior20), default=None)
    if prior20_high == float("-inf"):
        prior20_high = None
    if prior20_low == float("inf"):
        prior20_low = None
    return {
        "historical_close": historical_close,
        "close": historical_close,
        "sma20": sma(closes, 20),
        "sma50": sma(closes, 50),
        "sma200": sma(closes, 200),
        "ema20": ema(closes, 20),
        "atr14": atr(bars, 14),
        "ret5": pct_change(historical_close, closes[-6] if len(closes) >= 6 else None),
        "ret20": pct_change(historical_close, closes[-21] if len(closes) >= 21 else None),
        "prior20_high": prior20_high,
        "prior20_low": prior20_low,
        "high52w": max(highs[-252:]) if highs else None,
        "low52w": min(lows[-252:]) if lows else None,
        "prev_high": num(bars[-1].get("h")) if bars else None,
        "prev_low": num(bars[-1].get("l")) if bars else None,
        "prev_close": historical_close,
    }


def weekly_from_daily(bars: list[dict]) -> list[dict]:
    groups: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for bar in bars:
        t = bar.get("t")
        if t is None:
            continue
        dt = ts_to_et(int(t))
        iso = dt.isocalendar()
        groups[(iso.year, iso.week)].append(bar)
    result = []
    for key in sorted(groups):
        rows = groups[key]
        result.append({
            "t": rows[0].get("t"),
            "o": rows[0].get("o"),
            "h": max(num(x.get("h"), float("-inf")) for x in rows),
            "l": min(num(x.get("l"), float("inf")) for x in rows),
            "c": rows[-1].get("c"),
            "v": sum(num(x.get("v"), 0) or 0 for x in rows),
        })
    return result


def four_hour_from_minutes(bars: list[dict]) -> list[dict]:
    """Build extended-hours-aware 4H blocks anchored at 04:00 ET.

    This is deliberately documented because it is not identical to every
    charting platform's 4H candle boundaries.
    """
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for bar in bars:
        t = bar.get("t")
        if t is None:
            continue
        dt = ts_to_et(int(t))
        if dt.hour < 4 or dt.hour >= 20:
            continue
        block = (dt.hour - 4) // 4
        groups[(dt.date().isoformat(), block)].append(bar)
    result = []
    for key in sorted(groups):
        rows = groups[key]
        result.append({
            "t": rows[0].get("t"),
            "o": rows[0].get("o"),
            "h": max(num(x.get("h"), float("-inf")) for x in rows),
            "l": min(num(x.get("l"), float("inf")) for x in rows),
            "c": rows[-1].get("c"),
            "v": sum(num(x.get("v"), 0) or 0 for x in rows),
        })
    return result


def trend_label(close: float | None, *averages: float | None) -> str:
    if close is None:
        return "UNKNOWN"
    available = [x for x in averages if x is not None]
    if not available:
        return "UNKNOWN"
    above = sum(close > x for x in available)
    below = sum(close < x for x in available)
    if above == len(available):
        return "BULLISH"
    if below == len(available):
        return "BEARISH"
    return "NEUTRAL"


def technical_bundle(daily_bars: list[dict], minute_bars: list[dict], current_price: float, current_date: date) -> dict:
    completed = completed_daily_bars(daily_bars, current_date)
    daily = daily_metrics(completed)
    weekly_bars = weekly_from_daily(completed)
    weekly_closes = [num(x.get("c")) for x in weekly_bars]
    weekly_closes = [x for x in weekly_closes if x is not None]
    four_bars = four_hour_from_minutes(minute_bars)
    four_closes = [num(x.get("c")) for x in four_bars]
    four_closes = [x for x in four_closes if x is not None]

    weekly = {
        "reference_close": weekly_closes[-1] if weekly_closes else None,
        "sma10": sma(weekly_closes, 10),
        "sma30": sma(weekly_closes, 30),
    }
    weekly["trend"] = trend_label(current_price, weekly["sma10"], weekly["sma30"])

    four = {
        "close": four_closes[-1] if four_closes else None,
        "ema20": ema(four_closes, 20),
        "sma50": sma(four_closes, 50),
        "bar_definition": "4H blocks anchored at 04:00 ET, extended hours included",
    }
    four["trend"] = trend_label(current_price, four["ema20"], four["sma50"])

    daily["current_price"] = current_price
    daily["trend"] = trend_label(current_price, daily.get("ema20"), daily.get("sma50"), daily.get("sma200"))
    return {"weekly": weekly, "daily": daily, "four_hour": four}


def technical_direction_score(bundle: dict, direction: str, current_price: float) -> float:
    score = 0.0
    desired = "BULLISH" if direction == "LONG" else "BEARISH"
    for label, pts in (("weekly", 6), ("daily", 11), ("four_hour", 5)):
        trend = bundle.get(label, {}).get("trend")
        if trend == desired:
            score += pts
        elif trend == "NEUTRAL":
            score += pts * 0.25

    d = bundle.get("daily", {})
    pivot = d.get("prior20_high") if direction == "LONG" else d.get("prior20_low")
    if pivot is not None:
        if direction == "LONG" and current_price >= pivot:
            score += 3
        if direction == "SHORT" and current_price <= pivot:
            score += 3
    return round(min(score, 25.0), 1)
