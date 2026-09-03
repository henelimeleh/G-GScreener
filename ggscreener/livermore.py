from __future__ import annotations


def livermore_score(
    direction: str,
    price: float,
    technical: dict,
    session: dict,
    volume: dict,
    market_score: float,
    sector_score: float,
    extended_vwap_pct: float,
) -> tuple[float, dict]:
    """Translate Livermore-style confirmation into observable behavior.

    V2.1 deliberately avoids awarding a second full set of points for market
    and sector because those already have dedicated score buckets. They remain
    contextual warnings/reasons here. The Livermore bucket is therefore mostly
    about price confirmation, favorable progress and avoiding forced/chased
    entries, with volume/VWAP as modern confirmation overlays.
    """
    points = 0.0
    reasons: list[str] = []
    warnings: list[str] = []

    desired = "BULLISH" if direction == "LONG" else "BEARISH"
    aligned = sum(
        1
        for tf in ("weekly", "daily", "four_hour")
        if technical.get(tf, {}).get("trend") == desired
    )
    if aligned == 3:
        points += 3.0
        reasons.append("Weekly/Daily/4H align with the direction of least resistance")
    elif aligned == 2:
        points += 2.0
        reasons.append("Two of three major timeframes align")
    elif aligned == 1:
        points += 0.5
    else:
        warnings.append("No multi-timeframe confirmation")

    # Context only here; market/sector points already exist elsewhere.
    if market_score >= 7:
        reasons.append("Broad market supports the directional thesis")
    elif market_score < 4:
        warnings.append("Broad market fights the thesis")
    if sector_score >= 7:
        reasons.append("Sector confirms the thesis")
    elif sector_score < 4:
        warnings.append("Sector fights the thesis")

    prior_pivot = session.get("prior_pm_high") if direction == "LONG" else session.get("prior_pm_low")
    if prior_pivot is None:
        d = technical.get("daily", {})
        prior_pivot = d.get("prior20_high") if direction == "LONG" else d.get("prior20_low")

    pivot_confirmed = False
    progress_from_pivot_pct = None
    if prior_pivot is not None and prior_pivot > 0:
        if direction == "LONG" and price > prior_pivot:
            pivot_confirmed = True
            progress_from_pivot_pct = (price / prior_pivot - 1) * 100
        elif direction == "SHORT" and price < prior_pivot:
            pivot_confirmed = True
            progress_from_pivot_pct = (prior_pivot / price - 1) * 100

    if pivot_confirmed:
        points += 5.0
        reasons.append("Price has crossed a meaningful pivot; thesis is price-confirmed")
        # Livermore adds after favorable progress, but not after a runaway move.
        atr = technical.get("daily", {}).get("atr14")
        if atr and atr > 0:
            progress_points = abs(price - prior_pivot) / atr
            if 0.05 <= progress_points <= 0.75:
                points += 1.5
                reasons.append("Price has made favorable progress beyond the pivot without excessive extension")
            elif progress_points > 1.5:
                warnings.append("Price has already traveled far beyond the pivot; confirmation may be too late to chase")
    else:
        warnings.append("Price has not yet confirmed through the key pivot")

    recent = volume.get("recent_5m_rvol")
    runtime = volume.get("runtime_rvol")
    if (recent is not None and recent >= 2) or (runtime is not None and runtime >= 3):
        points += 1.5
        reasons.append("Volume confirms participation")

    vwap = session.get("vwap")
    distance = None
    if vwap and vwap > 0:
        distance = (price / vwap - 1) * 100
        direction_ok = (direction == "LONG" and price >= vwap) or (direction == "SHORT" and price <= vwap)
        if direction_ok:
            points += 2.0
            reasons.append("Price is on the correct side of session VWAP")
        else:
            warnings.append("Price is on the wrong side of session VWAP")

        if abs(distance) <= extended_vwap_pct:
            points += 2.0
        else:
            points -= 2.0
            warnings.append("Price is extended from VWAP; do not chase")

    score = max(0, min(15, points))
    return round(score, 1), {
        "score": round(score, 1),
        "pivot": prior_pivot,
        "pivot_confirmed": pivot_confirmed,
        "progress_from_pivot_pct": progress_from_pivot_pct,
        "timeframes_aligned": aligned,
        "reasons": reasons,
        "warnings": warnings,
        "add_rule": "Only consider adding after favorable price progress / a new confirmed pivot; never average down into invalidation.",
        "book_principle": "Wait for the market to prove the thesis; do not trade because a stock merely looks cheap or expensive.",
    }
