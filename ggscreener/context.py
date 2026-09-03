from __future__ import annotations

from .technicals import daily_metrics, trend_label


def trend_strength(metrics: dict) -> float | None:
    close = metrics.get("close")
    if close is None:
        return None
    checks = [x for x in (metrics.get("sma20"), metrics.get("sma50"), metrics.get("sma200")) if x is not None]
    if not checks:
        return None
    return sum(close > ma for ma in checks) / len(checks)


def market_context(
    spy_bars: list[dict],
    qqq_bars: list[dict],
    spy_current_change: float | None = None,
    qqq_current_change: float | None = None,
) -> dict:
    spy = daily_metrics(spy_bars)
    qqq = daily_metrics(qqq_bars)
    strengths = [x for x in (trend_strength(spy), trend_strength(qqq)) if x is not None]
    available = bool(strengths)
    bull = sum(strengths) / len(strengths) if strengths else None

    # Intraday/current snapshot context is intentionally a small overlay, not
    # a replacement for the structural trend.
    current_values = [x for x in (spy_current_change, qqq_current_change) if x is not None]
    current_breadth = None
    if current_values:
        current_breadth = sum(1 if x > 0 else 0 for x in current_values) / len(current_values)

    blended = bull
    if bull is not None and current_breadth is not None:
        blended = 0.75 * bull + 0.25 * current_breadth
    elif bull is None and current_breadth is not None:
        blended = current_breadth

    if blended is None:
        regime = "UNKNOWN"
    elif blended >= 0.70:
        regime = "RISK_ON"
    elif blended <= 0.30:
        regime = "RISK_OFF"
    else:
        regime = "MIXED"

    return {
        "available": available or bool(current_values),
        "regime": regime,
        "spy": spy,
        "qqq": qqq,
        "bullishness": blended,
        "spy_current_change_pct": spy_current_change,
        "qqq_current_change_pct": qqq_current_change,
        "macro": "NOT_DIRECTLY_SCORED",
        "note": "Price-based market regime only. Fed/CPI/yields require a separate macro source.",
    }


def market_score(ctx: dict, direction: str) -> float:
    bull = ctx.get("bullishness")
    if bull is None:
        return 0.0
    bull = float(bull)
    value = bull if direction == "LONG" else 1 - bull
    return round(max(0, min(10, value * 10)), 1)


def sector_context(
    etf: str,
    etf_bars: list[dict],
    spy_bars: list[dict],
    etf_current_change: float | None = None,
    spy_current_change: float | None = None,
) -> dict:
    sec = daily_metrics(etf_bars)
    spy = daily_metrics(spy_bars)
    sec["trend"] = trend_label(sec.get("close"), sec.get("sma20"), sec.get("sma50"), sec.get("sma200"))
    rel5 = None
    rel20 = None
    if sec.get("ret5") is not None and spy.get("ret5") is not None:
        rel5 = sec["ret5"] - spy["ret5"]
    if sec.get("ret20") is not None and spy.get("ret20") is not None:
        rel20 = sec["ret20"] - spy["ret20"]
    current_vs_spy = None
    if etf_current_change is not None and spy_current_change is not None:
        current_vs_spy = etf_current_change - spy_current_change
    return {
        "available": bool(sec),
        "etf": etf,
        "trend": sec.get("trend", "UNKNOWN"),
        "ret5": sec.get("ret5"),
        "ret20": sec.get("ret20"),
        "vs_spy_5d": rel5,
        "vs_spy_20d": rel20,
        "current_change_pct": etf_current_change,
        "current_vs_spy": current_vs_spy,
        "metrics": sec,
    }


def sector_score(ctx: dict, direction: str) -> float:
    if not ctx.get("available"):
        return 0.0
    score = 4.0
    trend = ctx.get("trend")
    if direction == "LONG":
        if trend == "BULLISH":
            score += 2.5
        elif trend == "BEARISH":
            score -= 2.5
        for key in ("current_vs_spy", "vs_spy_5d", "vs_spy_20d"):
            value = ctx.get(key)
            if value is not None:
                score += 1.0 if value > 0 else -1.0
    else:
        if trend == "BEARISH":
            score += 2.5
        elif trend == "BULLISH":
            score -= 2.5
        for key in ("current_vs_spy", "vs_spy_5d", "vs_spy_20d"):
            value = ctx.get(key)
            if value is not None:
                score += 1.0 if value < 0 else -1.0
    return round(max(0, min(10, score)), 1)


def relative_strength(
    stock_daily: dict,
    spy_daily: dict,
    sector_daily: dict,
    stock_current_change: float,
    spy_current_change: float | None,
    sector_current_change: float | None,
) -> dict:
    out = {
        "current_vs_spy": None,
        "current_vs_sector": None,
        "stock_vs_spy_5d": None,
        "stock_vs_spy_20d": None,
        "stock_vs_sector_5d": None,
        "stock_vs_sector_20d": None,
    }
    if spy_current_change is not None:
        out["current_vs_spy"] = stock_current_change - spy_current_change
    if sector_current_change is not None:
        out["current_vs_sector"] = stock_current_change - sector_current_change
    if stock_daily.get("ret5") is not None and spy_daily.get("ret5") is not None:
        out["stock_vs_spy_5d"] = stock_daily["ret5"] - spy_daily["ret5"]
    if stock_daily.get("ret20") is not None and spy_daily.get("ret20") is not None:
        out["stock_vs_spy_20d"] = stock_daily["ret20"] - spy_daily["ret20"]
    if stock_daily.get("ret5") is not None and sector_daily.get("ret5") is not None:
        out["stock_vs_sector_5d"] = stock_daily["ret5"] - sector_daily["ret5"]
    if stock_daily.get("ret20") is not None and sector_daily.get("ret20") is not None:
        out["stock_vs_sector_20d"] = stock_daily["ret20"] - sector_daily["ret20"]
    return out


def relative_strength_score(ctx: dict, direction: str) -> float:
    keys = (
        "current_vs_spy",
        "current_vs_sector",
        "stock_vs_spy_5d",
        "stock_vs_spy_20d",
        "stock_vs_sector_5d",
        "stock_vs_sector_20d",
    )
    values = [ctx.get(k) for k in keys if ctx.get(k) is not None]
    if not values:
        return 0.0
    signs = [v > 0 for v in values]
    ratio = sum(signs) / len(signs)
    if direction == "SHORT":
        ratio = 1 - ratio
    magnitude = sum(min(abs(v), 10) for v in values) / (10 * len(values))
    return round(min(10, ratio * 7 + magnitude * 3), 1)
