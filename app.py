from __future__ import annotations

import argparse
import csv
import json
import os
import time as sleep_time
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / "cache"
OUTPUT = ROOT / "output"
ET = ZoneInfo("America/New_York")


class APIError(RuntimeError):
    pass


class Massive:
    def __init__(self):
        key = os.getenv("MASSIVE_API_KEY", "").strip()
        if not key or key == "PUT_YOUR_MASSIVE_API_KEY_HERE":
            raise RuntimeError("Set MASSIVE_API_KEY in .env first.")
        self.key = key
        self.base = os.getenv(
            "MASSIVE_BASE_URL", "https://api.massive.com"
        ).rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({
            "Accept": "application/json",
            "User-Agent": "gap-go-watchlist-v1.1",
        })

    def get(self, path, **params):
        params["apiKey"] = self.key
        try:
            r = self.s.get(self.base + path, params=params, timeout=30)
        except requests.RequestException as exc:
            raise APIError(str(exc)) from exc

        if r.status_code >= 400:
            body = r.text[:600].replace(self.key, "***")
            raise APIError(f"HTTP {r.status_code}: {body}")

        try:
            return r.json()
        except ValueError as exc:
            raise APIError("Massive returned non-JSON data") from exc

    def snapshot(self):
        data = self.get(
            "/v2/snapshot/locale/us/markets/stocks/tickers",
            include_otc="false",
        )
        return data.get("tickers", []) or []

    def overview(self, ticker):
        data = self.get(f"/v3/reference/tickers/{ticker}")
        return data.get("results", {}) or {}

    def grouped_day(self, day):
        data = self.get(
            f"/v2/aggs/grouped/locale/us/market/stocks/{day}",
            adjusted="true",
            include_otc="false",
        )
        return data.get("results", []) or []


def number(value, default=None):
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def compact(value):
    if value is None:
        return "N/A"
    value = float(value)
    if abs(value) >= 1e12:
        return f"{value/1e12:.2f}T"
    if abs(value) >= 1e9:
        return f"{value/1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"{value/1e6:.2f}M"
    if abs(value) >= 1e3:
        return f"{value/1e3:.1f}K"
    return f"{value:.0f}"


def normalize_snapshot(raw):
    ticker = raw.get("ticker")
    if not ticker:
        return None

    day = raw.get("day") or {}
    prev = raw.get("prevDay") or {}
    minute = raw.get("min") or {}
    trade = raw.get("lastTrade") or {}

    # Massive Starter: min.c is our preferred latest delayed price.
    price = number(minute.get("c"))
    if price is None:
        price = number(trade.get("p"))
    if price is None:
        price = number(day.get("c"))

    prev_close = number(prev.get("c"))

    # Massive Starter: min.av is today's accumulated volume.
    volume = number(minute.get("av"))
    if volume is None:
        volume = number(day.get("v"), 0) or 0

    # Massive provides current % change vs previous close.
    gap = number(raw.get("todaysChangePerc"))

    # Defensive fallback.
    if gap is None and price is not None and prev_close and prev_close > 0:
        gap = (price / prev_close - 1) * 100

    return {
        "ticker": str(ticker),
        "price": price,
        "prev_close": prev_close,
        "volume": volume,
        "gap": gap,
    }


def premarket_now():
    t = datetime.now(ET).time()
    return time(4, 0) <= t < time(9, 30)


def history_cache_path(day):
    return CACHE / f"daily-{day}.json"


def get_history(client, sessions, before):
    CACHE.mkdir(exist_ok=True)
    result = []
    offset = 1

    while len(result) < sessions and offset <= 50:
        d = before - timedelta(days=offset)
        offset += 1

        if d.weekday() >= 5:
            continue

        p = history_cache_path(d.isoformat())
        if p.exists():
            try:
                rows = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                rows = []
        else:
            rows = client.grouped_day(d.isoformat())
            p.write_text(json.dumps(rows), encoding="utf-8")

        if rows:
            result.append(rows)

    if len(result) < sessions:
        raise RuntimeError(f"Found only {len(result)} sessions; need {sessions}.")

    return result


def average_volumes(history):
    values = defaultdict(list)

    for rows in history:
        for row in rows:
            ticker = row.get("T")
            volume = number(row.get("v"))
            if ticker and volume is not None and volume >= 0:
                values[str(ticker)].append(volume)

    return {
        ticker: sum(volumes) / len(volumes)
        for ticker, volumes in values.items()
        if volumes
    }


def metadata_cache_load():
    p = CACHE / "metadata.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_meta(client, cache, ticker):
    cached = cache.get(ticker)
    if cached:
        return cached

    raw = client.overview(ticker)
    cache[ticker] = raw

    CACHE.mkdir(exist_ok=True)
    (CACHE / "metadata.json").write_text(
        json.dumps(cache, indent=2),
        encoding="utf-8",
    )

    sleep_time.sleep(0.02)
    return raw


def mcap_band(mcap):
    if mcap >= 10e9:
        return "LARGE+"
    if mcap >= 5e9:
        return "LARGE"
    return "MID"


def scan(snapshot, avgs, client, args, is_pm):
    meta_cache = metadata_cache_load()

    gap_up_list = []
    gap_down_list = []
    rvol_list = []
    rejected = []

    candidates = []

    for raw in snapshot:
        s = normalize_snapshot(raw)

        if not s or s["price"] is None or s["price"] <= args.min_price:
            continue

        avg = avgs.get(s["ticker"])
        rvol = s["volume"] / avg if avg and avg > 0 else None

        gap_up_candidate = (
            is_pm
            and s["gap"] is not None
            and s["gap"] >= args.min_gap_up
            and s["volume"] >= args.min_pm_volume
        )

        gap_down_candidate = (
            is_pm
            and s["gap"] is not None
            and s["gap"] <= -args.min_gap_down
            and s["volume"] >= args.min_pm_volume
        )

        rvol_candidate = rvol is not None and rvol >= args.min_rvol

        if gap_up_candidate or gap_down_candidate or rvol_candidate:
            s["avg_volume"] = avg
            s["rvol"] = rvol
            candidates.append(s)

    for s in candidates:
        meta = get_meta(client, meta_cache, s["ticker"])

        mcap = number(meta.get("market_cap"))
        ticker_type = str(meta.get("type") or "").upper()
        active = bool(meta.get("active", True))

        if not active:
            rejected.append((s["ticker"], "inactive"))
            continue

        if ticker_type != "CS":
            rejected.append((s["ticker"], f"type={ticker_type or 'unknown'}"))
            continue

        if mcap is None or mcap < args.min_market_cap:
            rejected.append((s["ticker"], "market cap below threshold"))
            continue

        base = {
            "ticker": s["ticker"],
            "name": meta.get("name") or "",
            "price": s["price"],
            "market_cap": mcap,
            "market_cap_band": mcap_band(mcap),
            "gap_pct": s["gap"],
        }

        if (
            is_pm
            and s["gap"] is not None
            and s["gap"] >= args.min_gap_up
            and s["volume"] >= args.min_pm_volume
        ):
            item = dict(base)
            item.update({
                "category": "GAP UP + PM VOLUME",
                "pm_volume": s["volume"],
                "current_volume": s["volume"],
                "avg_volume": s["avg_volume"],
                "rvol": s["rvol"],
                "why": [
                    f"Gap Up {s['gap']:+.2f}% >= +{args.min_gap_up:.1f}%",
                    f"PM Volume {s['volume']:,.0f} >= {args.min_pm_volume:,.0f}",
                ],
            })
            gap_up_list.append(item)

        if (
            is_pm
            and s["gap"] is not None
            and s["gap"] <= -args.min_gap_down
            and s["volume"] >= args.min_pm_volume
        ):
            item = dict(base)
            item.update({
                "category": "GAP DOWN + PM VOLUME",
                "pm_volume": s["volume"],
                "current_volume": s["volume"],
                "avg_volume": s["avg_volume"],
                "rvol": s["rvol"],
                "why": [
                    f"Gap Down {s['gap']:+.2f}% <= -{args.min_gap_down:.1f}%",
                    f"PM Volume {s['volume']:,.0f} >= {args.min_pm_volume:,.0f}",
                ],
            })
            gap_down_list.append(item)

        if s["rvol"] is not None and s["rvol"] >= args.min_rvol:
            item = dict(base)
            item.update({
                "category": "RELATIVE VOLUME",
                "pm_volume": s["volume"] if is_pm else None,
                "current_volume": s["volume"],
                "avg_volume": s["avg_volume"],
                "rvol": s["rvol"],
                "why": [
                    (
                        f"Current Volume {s['volume']:,.0f} / "
                        f"{args.lookback}-session avg {s['avg_volume']:,.0f} "
                        f"= {s['rvol']:.1f}x"
                    ),
                    f"RVOL {s['rvol']:.1f}x >= {args.min_rvol:.1f}x",
                ],
            })
            rvol_list.append(item)

    gap_up_list.sort(
        key=lambda x: (x["gap_pct"] or 0, x["pm_volume"] or 0),
        reverse=True,
    )

    gap_down_list.sort(
        key=lambda x: (
            x["gap_pct"] if x["gap_pct"] is not None else 0,
            -(x["pm_volume"] or 0),
        )
    )

    rvol_list.sort(key=lambda x: x["rvol"] or 0, reverse=True)

    return gap_up_list, gap_down_list, rvol_list, rejected


def print_section(title, icon, items):
    print(f"\n{icon} {title}")
    print("=" * 90)

    if not items:
        print("No qualifying stocks.")
        return

    for i, x in enumerate(items, 1):
        print(
            f"{i:>2}. {x['ticker']:<7} "
            f"${x['price']:>9.2f} | "
            f"MCAP ${compact(x['market_cap']):>7} "
            f"[{x['market_cap_band']}]"
        )

        if "PM VOLUME" in x["category"]:
            print(
                f"    Gap {x['gap_pct']:+.2f}% | "
                f"PM Volume {compact(x['pm_volume'])}"
            )
        else:
            gap = (
                f"{x['gap_pct']:+.2f}%"
                if x["gap_pct"] is not None
                else "N/A"
            )
            print(
                f"    RVOL {x['rvol']:.1f}x | "
                f"Volume {compact(x['current_volume'])} | "
                f"Normal {compact(x['avg_volume'])} | Gap {gap}"
            )

        print("    WHY: " + "; ".join(x["why"]))


def save_output(gap_up, gap_down, rvol, args, is_pm):
    OUTPUT.mkdir(exist_ok=True)

    payload = {
        "timestamp_et": datetime.now(ET).isoformat(),
        "premarket_gap_categories_enabled": is_pm,
        "rules": {
            "min_price": args.min_price,
            "min_market_cap": args.min_market_cap,
            "min_gap_up_pct": args.min_gap_up,
            "min_gap_down_pct": args.min_gap_down,
            "min_pm_volume": args.min_pm_volume,
            "min_rvol": args.min_rvol,
            "lookback": args.lookback,
        },
        "gap_up_premarket_volume": gap_up,
        "gap_down_premarket_volume": gap_down,
        "relative_volume": rvol,
    }

    (OUTPUT / "watchlist.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    rows = gap_up + gap_down + rvol
    fields = [
        "ticker", "name", "category", "price", "market_cap",
        "market_cap_band", "gap_pct", "pm_volume",
        "current_volume", "avg_volume", "rvol", "why",
    ]

    with (OUTPUT / "watchlist.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for row in rows:
            exported = dict(row)
            exported["why"] = "; ".join(exported.get("why") or [])
            writer.writerow(exported)


def demo():
    gap_up = [{
        "ticker": "UPX",
        "name": "Gap Up Example",
        "category": "GAP UP + PM VOLUME",
        "price": 55.0,
        "market_cap": 18e9,
        "market_cap_band": "LARGE+",
        "gap_pct": 10.0,
        "pm_volume": 1.8e6,
        "current_volume": 1.8e6,
        "avg_volume": 5e6,
        "rvol": 0.36,
        "why": [
            "Gap Up +10.00% >= +5.0%",
            "PM Volume 1,800,000 >= 1,000,000",
        ],
    }]

    gap_down = [{
        "ticker": "DNX",
        "name": "Gap Down Example",
        "category": "GAP DOWN + PM VOLUME",
        "price": 42.0,
        "market_cap": 9e9,
        "market_cap_band": "LARGE",
        "gap_pct": -8.5,
        "pm_volume": 2.4e6,
        "current_volume": 2.4e6,
        "avg_volume": 4e6,
        "rvol": 0.6,
        "why": [
            "Gap Down -8.50% <= -5.0%",
            "PM Volume 2,400,000 >= 1,000,000",
        ],
    }]

    rvol = [{
        "ticker": "RVX",
        "name": "RVOL Example",
        "category": "RELATIVE VOLUME",
        "price": 25.0,
        "market_cap": 7.5e9,
        "market_cap_band": "LARGE",
        "gap_pct": 2.0,
        "pm_volume": 8e6,
        "current_volume": 8e6,
        "avg_volume": 1.2e6,
        "rvol": 6.67,
        "why": [
            "Current Volume 8,000,000 / 20-session avg 1,200,000 = 6.7x",
            "RVOL 6.7x >= 5.0x",
        ],
    }]

    return gap_up, gap_down, rvol


def parse_args():
    p = argparse.ArgumentParser(description="Gap & Go Watchlist V1.1")

    p.add_argument("--demo", action="store_true")
    p.add_argument("--smoke-test", action="store_true")

    p.add_argument(
        "--min-price",
        type=float,
        default=float(os.getenv("MIN_PRICE", "5")),
    )
    p.add_argument(
        "--min-market-cap",
        type=float,
        default=float(os.getenv("MIN_MARKET_CAP", "2000000000")),
    )
    p.add_argument(
        "--min-gap-up",
        type=float,
        default=float(os.getenv("MIN_GAP_UP_PCT", "5")),
    )
    p.add_argument(
        "--min-gap-down",
        type=float,
        default=float(os.getenv("MIN_GAP_DOWN_PCT", "5")),
    )
    p.add_argument(
        "--min-pm-volume",
        type=float,
        default=float(os.getenv("MIN_PREMARKET_VOLUME", "1000000")),
    )
    p.add_argument(
        "--min-rvol",
        type=float,
        default=float(os.getenv("MIN_RVOL", "5")),
    )
    p.add_argument(
        "--lookback",
        type=int,
        default=int(os.getenv("RVOL_LOOKBACK_SESSIONS", "20")),
    )

    return p.parse_args()


def smoke_test():
    c = Massive()

    print("Testing Full Market Snapshot...")
    snap = c.snapshot()
    print(f"✅ Snapshot: {len(snap):,} ticker(s)")

    populated_av = sum(
        1
        for raw in snap
        if number((raw.get("min") or {}).get("av"), 0) > 0
    )
    populated_change = sum(
        1
        for raw in snap
        if raw.get("todaysChangePerc") is not None
    )

    print(f"✅ min.av populated: {populated_av:,} ticker(s)")
    print(f"✅ todaysChangePerc populated: {populated_change:,} ticker(s)")

    print("Testing AAPL Ticker Overview...")
    meta = c.overview("AAPL")
    print(
        f"✅ Overview: {meta.get('name', 'AAPL')} | "
        f"type={meta.get('type')} | "
        f"mcap={meta.get('market_cap')}"
    )

    d = date.today() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)

    print(f"Testing grouped daily data for {d}...")
    rows = c.grouped_day(d.isoformat())
    print(f"✅ Grouped daily: {len(rows):,} row(s)")


def main():
    args = parse_args()

    if args.smoke_test:
        smoke_test()
        return

    if args.demo:
        gap_up, gap_down, rvol = demo()
        rejected = []
        is_pm = True
    else:
        client = Massive()
        now = datetime.now(ET)
        is_pm = premarket_now()

        print("Fetching full-market snapshot...")
        snapshot = client.snapshot()
        print(f"Snapshot: {len(snapshot):,} ticker(s)")

        print(f"Building {args.lookback}-session volume baseline...")
        history = get_history(client, args.lookback, now.date())
        avgs = average_volumes(history)
        print(f"Volume baseline: {len(avgs):,} ticker(s)")

        gap_up, gap_down, rvol, rejected = scan(
            snapshot, avgs, client, args, is_pm
        )

    print("\nMARKET WATCHLIST V1.1")
    print(
        f"Active filters: Common Stock | "
        f"Price > ${args.min_price:g} | "
        f"Market Cap >= ${compact(args.min_market_cap)}"
    )
    print(
        f"Premarket: Gap Up >= +{args.min_gap_up:g}% OR "
        f"Gap Down <= -{args.min_gap_down:g}% | "
        f"PM Volume >= {compact(args.min_pm_volume)}"
    )
    print(
        f"RVOL >= {args.min_rvol:g}x | "
        f"Lookback {args.lookback} sessions"
    )
    print("Massive Starter data may be ~15 minutes delayed.")

    if not is_pm:
        print(
            "NOTE: Gap Up/Down PM categories are disabled "
            "outside 04:00–09:30 ET."
        )

    print_section("GAP UP + PREMARKET VOLUME", "🔥", gap_up)
    print_section("GAP DOWN + PREMARKET VOLUME", "🔻", gap_down)
    print_section("RELATIVE VOLUME", "⚡", rvol)

    gap_tickers = {x["ticker"] for x in gap_up + gap_down}
    rvol_tickers = {x["ticker"] for x in rvol}
    overlap = sorted(gap_tickers & rvol_tickers)

    print(
        "\n🔥/🔻 + ⚡ BOTH:",
        ", ".join(overlap) if overlap else "None",
    )

    if rejected:
        print(f"Metadata gate rejected {len(rejected)} candidate(s).")

    save_output(gap_up, gap_down, rvol, args, is_pm)

    print("\nSaved output/watchlist.json")
    print("Saved output/watchlist.csv")


if __name__ == "__main__":
    main()
