from __future__ import annotations

from datetime import datetime, time
from statistics import median
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def num(value, default=None):
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def compact(value: float | None) -> str:
    if value is None:
        return "N/A"
    n = float(value)
    for divisor, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= divisor:
            return f"{n/divisor:.2f}{suffix}"
    return f"{n:.0f}"


def ts_to_et(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).astimezone(ET)


def parse_hhmm(value: str) -> time:
    hh, mm = value.split(":", 1)
    return time(int(hh), int(mm))


def safe_median(values: list[float]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    return median(clean) if clean else None


def pct_change(new: float | None, old: float | None) -> float | None:
    if new is None or old in (None, 0):
        return None
    return (new / old - 1.0) * 100.0


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))
