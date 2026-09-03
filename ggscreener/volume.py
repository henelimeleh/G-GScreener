from __future__ import annotations

from collections import defaultdict
from datetime import time, timedelta
from statistics import median

from .utils import parse_hhmm, ts_to_et, num


def pm_volume_state(volume: float, watch: int, active: int, strong: int, qualified: int) -> str:
    if volume >= qualified:
        return "QUALIFIED"
    if volume >= strong:
        return "STRONG"
    if volume >= active:
        return "ACTIVE"
    if volume >= watch:
        return "WATCH"
    return "LOW"


def _volume_in_clock_window(rows: list[dict], start_time, end_time) -> float:
    total = 0.0
    for row in rows:
        t = row.get("t")
        if t is None:
            continue
        dt = ts_to_et(int(t))
        tt = dt.time().replace(tzinfo=None)
        if start_time <= tt <= end_time:
            total += num(row.get("v"), 0) or 0
    return total


def runtime_rvol(
    minute_bars: list[dict],
    current_date,
    premarket_start_hhmm: str,
    rth_start_hhmm: str,
    lookback: int,
) -> dict:
    """Same-clock-time RVOL using the median of previous sessions.

    Before 09:30 ET the comparison starts at the configured premarket start.
    At/after 09:30 ET it automatically switches to an RTH-only comparison so
    a huge premarket event does not mask (or manufacture) current regular-hour
    participation.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in minute_bars:
        if row.get("t") is None:
            continue
        grouped[ts_to_et(int(row["t"])).date().isoformat()].append(row)

    today_key = current_date.isoformat()
    today = sorted(grouped.get(today_key, []), key=lambda x: x.get("t", 0))
    if not today:
        return {
            "runtime_rvol": None,
            "recent_5m_rvol": None,
            "cutoff": None,
            "baseline": None,
            "session_start": None,
            "history_sessions": 0,
        }

    cutoff_dt = ts_to_et(int(today[-1]["t"]))
    cutoff_time = cutoff_dt.time().replace(tzinfo=None)
    rth_start = parse_hhmm(rth_start_hhmm)
    pre_start = parse_hhmm(premarket_start_hhmm)
    start_time = rth_start if cutoff_time >= rth_start else pre_start
    session_name = "RTH" if start_time == rth_start else "PREMARKET"

    # If data is older than the requested session start, do not manufacture 0x.
    if cutoff_time < start_time:
        return {
            "runtime_rvol": None,
            "recent_5m_rvol": None,
            "cutoff": cutoff_dt.strftime("%Y-%m-%d %H:%M ET"),
            "baseline": None,
            "session_start": start_time.strftime("%H:%M"),
            "session_name": session_name,
            "history_sessions": 0,
        }

    current_total = _volume_in_clock_window(today, start_time, cutoff_time)
    hist_dates = sorted([k for k in grouped if k < today_key], reverse=True)[:lookback]
    hist_totals = []
    hist_5m = []

    window_start_dt = cutoff_dt - timedelta(minutes=4)
    window_start = window_start_dt.time().replace(tzinfo=None)
    recent_window_valid = window_start <= cutoff_time and window_start >= start_time

    for day in hist_dates:
        rows = grouped[day]
        value = _volume_in_clock_window(rows, start_time, cutoff_time)
        # Keep zero-volume observations. Excluding zeros inflates the baseline
        # for less-liquid names and understates how unusual current volume is.
        hist_totals.append(value)
        if recent_window_valid:
            hist_5m.append(_volume_in_clock_window(rows, window_start, cutoff_time))

    baseline = median(hist_totals) if hist_totals else None
    runtime = current_total / baseline if baseline and baseline > 0 else None

    current_5m = _volume_in_clock_window(today, window_start, cutoff_time) if recent_window_valid else None
    base_5m = median(hist_5m) if hist_5m else None
    recent = current_5m / base_5m if current_5m is not None and base_5m and base_5m > 0 else None

    return {
        "runtime_rvol": runtime,
        "recent_5m_rvol": recent,
        "cutoff": cutoff_dt.strftime("%Y-%m-%d %H:%M ET"),
        "current_volume": current_total,
        "baseline": baseline,
        "current_5m": current_5m,
        "baseline_5m": base_5m,
        "history_sessions": len(hist_totals),
        "session_start": start_time.strftime("%H:%M"),
        "session_name": session_name,
    }


def current_session_metrics(minute_bars: list[dict], current_date) -> dict:
    today = [x for x in minute_bars if x.get("t") and ts_to_et(int(x["t"])).date() == current_date]
    today.sort(key=lambda x: x.get("t", 0))
    if not today:
        return {
            "vwap": None,
            "pm_volume": None,
            "pm_high": None,
            "pm_low": None,
            "prior_pm_high": None,
            "prior_pm_low": None,
            "last_price": None,
            "last_ts": None,
        }

    pm = []
    for x in today:
        dt = ts_to_et(int(x["t"]))
        if time(4, 0) <= dt.time().replace(tzinfo=None) < time(9, 30):
            pm.append(x)

    def calc_vwap(rows):
        den = sum(num(x.get("v"), 0) or 0 for x in rows)
        if den <= 0:
            return None
        nume = sum((num(x.get("vw")) or num(x.get("c"), 0) or 0) * (num(x.get("v"), 0) or 0) for x in rows)
        return nume / den

    vwap = calc_vwap(today)
    pm_high = max((num(x.get("h")) for x in pm if num(x.get("h")) is not None), default=None)
    pm_low = min((num(x.get("l")) for x in pm if num(x.get("l")) is not None), default=None)

    # Exclude the newest 5 observed PM bars from the "prior" pivot so that a
    # fresh breakout can actually be detected instead of comparing price with
    # the high that includes the breakout bar itself.
    prior_pm = pm[:-5] if len(pm) > 5 else pm[:-1]
    prior_high = max((num(x.get("h")) for x in prior_pm if num(x.get("h")) is not None), default=None)
    prior_low = min((num(x.get("l")) for x in prior_pm if num(x.get("l")) is not None), default=None)
    pm_volume = sum(num(x.get("v"), 0) or 0 for x in pm)

    return {
        "vwap": vwap,
        "pm_volume": pm_volume,
        "pm_high": pm_high,
        "pm_low": pm_low,
        "prior_pm_high": prior_high,
        "prior_pm_low": prior_low,
        "last_price": num(today[-1].get("c")),
        "last_ts": today[-1].get("t"),
    }


def volume_score(runtime: float | None, recent: float | None, pm_state: str) -> float:
    score = 0.0
    if runtime is not None:
        if runtime >= 8:
            score += 10
        elif runtime >= 5:
            score += 8
        elif runtime >= 3:
            score += 6
        elif runtime >= 2:
            score += 4
        elif runtime >= 1.5:
            score += 2
    if recent is not None:
        if recent >= 8:
            score += 6
        elif recent >= 5:
            score += 5
        elif recent >= 3:
            score += 4
        elif recent >= 2:
            score += 3
        elif recent >= 1.5:
            score += 1.5
    score += {"QUALIFIED": 4, "STRONG": 3, "ACTIVE": 2, "WATCH": 1, "LOW": 0, "UNKNOWN": 0}.get(pm_state, 0)
    return round(min(score, 20.0), 1)
