from __future__ import annotations


def choose_setup(direction: str, gap_pct: float, technical: dict, current_price: float) -> str:
    d = technical.get("daily", {})
    if direction == "LONG" and gap_pct >= 5:
        return "GAP & GO LONG"
    if direction == "SHORT" and gap_pct <= -5:
        return "GAP & GO SHORT"
    if direction == "LONG" and d.get("prior20_high") is not None and current_price >= d.get("prior20_high"):
        return "PIVOT / BREAKOUT LONG"
    if direction == "SHORT" and d.get("prior20_low") is not None and current_price <= d.get("prior20_low"):
        return "PIVOT / BREAKDOWN SHORT"
    return "MOMENTUM WATCH"


def build_levels(direction: str, price: float, technical: dict, session: dict) -> dict:
    d = technical.get("daily", {})
    atr = d.get("atr14") or max(price * 0.02, 0.01)
    vwap = session.get("vwap")

    if direction == "LONG":
        pivot = session.get("prior_pm_high") or d.get("prior20_high") or session.get("pm_high") or price
        aggressive = pivot * 1.001
        confirmation_buffer = 0.15 * atr
        conservative = pivot + confirmation_buffer
        supports = [x for x in (vwap, session.get("pm_low"), d.get("prev_low"), d.get("ema20"), d.get("sma50")) if x is not None and x < aggressive]
        support = max(supports) if supports else aggressive - atr
        stop = max(0.01, support - 0.10 * atr)
        risk = max(aggressive - stop, 0.01)
        return {
            "pivot": pivot,
            "aggressive_trigger": aggressive,
            "aggressive_rule": "Break above pivot with participation; avoid entering if breakout immediately rejects.",
            "conservative_trigger": conservative,
            "conservative_rule": "Prefer a 5m close above pivot followed by a hold/retest; the static level is a reference, not a blind buy price.",
            "stop_reference": stop,
            "invalidation": support,
            "target_1r": aggressive + risk,
            "target_2r": aggressive + 2 * risk,
            "add_reference": conservative + 0.35 * atr,
            "add_rule": "Add only after favorable progress and renewed confirmation; never average down into invalidation.",
            "do_not_trade_if": "Price loses invalidation, breakout fails, participation disappears, or price is materially extended from VWAP before entry.",
        }

    pivot = session.get("prior_pm_low") or d.get("prior20_low") or session.get("pm_low") or price
    aggressive = pivot * 0.999
    confirmation_buffer = 0.15 * atr
    conservative = pivot - confirmation_buffer
    resistances = [x for x in (vwap, session.get("pm_high"), d.get("prev_high"), d.get("ema20"), d.get("sma50")) if x is not None and x > aggressive]
    resistance = min(resistances) if resistances else aggressive + atr
    stop = resistance + 0.10 * atr
    risk = max(stop - aggressive, 0.01)
    return {
        "pivot": pivot,
        "aggressive_trigger": aggressive,
        "aggressive_rule": "Break below pivot with participation; avoid entering if breakdown immediately reclaims.",
        "conservative_trigger": conservative,
        "conservative_rule": "Prefer a 5m close below pivot followed by a failed reclaim/retest; the static level is a reference, not a blind short price.",
        "stop_reference": stop,
        "invalidation": resistance,
        "target_1r": aggressive - risk,
        "target_2r": aggressive - 2 * risk,
        "add_reference": conservative - 0.35 * atr,
        "add_rule": "Add only after favorable progress and renewed confirmation; never average into invalidation.",
        "do_not_trade_if": "Price reclaims invalidation, breakdown fails, participation disappears, or price is materially extended from VWAP before entry.",
    }


def determine_state(
    score: float,
    direction: str,
    price: float,
    gap_pct: float,
    session: dict,
    livermore: dict,
    pm_state: str,
    volume: dict,
    armed_score: float,
    confirmed_score: float,
    extended_pct: float,
    runtime_arm_threshold: float,
    recent_5m_arm_threshold: float,
) -> str:
    vwap = session.get("vwap")
    if vwap and abs((price / vwap - 1) * 100) > extended_pct:
        return "EXTENDED"
    if direction == "LONG" and gap_pct >= 5 and price < (vwap or price):
        return "WATCH"
    if direction == "SHORT" and gap_pct <= -5 and price > (vwap or price):
        return "WATCH"

    runtime = volume.get("runtime_rvol")
    recent = volume.get("recent_5m_rvol")
    live_volume_confirmation = (
        (runtime is not None and runtime >= runtime_arm_threshold)
        or (recent is not None and recent >= recent_5m_arm_threshold)
        or pm_state in {"ACTIVE", "STRONG", "QUALIFIED"}
    )

    if score >= confirmed_score and livermore.get("pivot_confirmed") and live_volume_confirmation:
        return "CONFIRMED"
    if score >= armed_score and live_volume_confirmation:
        return "ARMED"
    return "WATCH"


def next_trigger_text(state: str, direction: str, levels: dict, livermore: dict) -> str:
    pivot = levels.get("pivot")
    invalidation = levels.get("invalidation")
    if state == "EXTENDED":
        return "Wait for a pullback/retest toward VWAP or structure; do not chase extension."
    if state == "CONFIRMED":
        return "Setup is price-confirmed; next requirement is continued hold/follow-through without losing invalidation."
    if not livermore.get("pivot_confirmed") and pivot is not None:
        verb = "above" if direction == "LONG" else "below"
        return f"Wait for price confirmation {verb} the pivot near ${pivot:.2f} with volume participation."
    if invalidation is not None:
        return f"Watch for continued participation while price respects invalidation near ${invalidation:.2f}."
    return "Wait for clearer price and volume confirmation."


def scenarios(direction: str, levels: dict, score: float) -> dict:
    base = max(35, min(75, 35 + (score - 50) * 0.8))
    directional = round(base, 1)
    neutral = round(max(15, 45 - abs(score - 50) * 0.4), 1)
    opposite = round(max(10, 100 - directional - neutral), 1)
    total = directional + neutral + opposite
    opposite = round(opposite + (100 - total), 1)
    meta = {"model": "HEURISTIC_NOT_CALIBRATED", "note": "Scenario percentages are score-derived heuristics, not backtested probabilities."}
    if direction == "LONG":
        return {
            "meta": meta,
            "bullish": {"probability_pct": directional, "trigger": f"Holds/clears {levels.get('pivot'):.2f}" if levels.get("pivot") else "Price confirms higher"},
            "neutral": {"probability_pct": neutral, "trigger": "Price remains around pivot/VWAP without follow-through"},
            "bearish": {"probability_pct": opposite, "trigger": f"Loses {levels.get('invalidation'):.2f}" if levels.get("invalidation") else "Thesis invalidates"},
        }
    return {
        "meta": meta,
        "bearish": {"probability_pct": directional, "trigger": f"Breaks/holds below {levels.get('pivot'):.2f}" if levels.get("pivot") else "Price confirms lower"},
        "neutral": {"probability_pct": neutral, "trigger": "Price remains around pivot/VWAP without follow-through"},
        "bullish": {"probability_pct": opposite, "trigger": f"Reclaims {levels.get('invalidation'):.2f}" if levels.get("invalidation") else "Thesis invalidates"},
    }
