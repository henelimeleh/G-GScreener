from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from .config import settings
from .demo import demo_reports
from .engine import V2Engine
from .massive import MassiveClient, MassiveError
from .output import print_detail, print_ranking, save
from .utils import ET


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="G-GScreener V2.1 — ranked stock discovery and setup engine")
    p.add_argument("--demo", action="store_true", help="Offline demo")
    p.add_argument("--smoke-test", action="store_true", help="Verify Massive endpoints")
    p.add_argument("--ticker", help="Analyze one ticker regardless of discovery ranking")
    p.add_argument("--top", type=int, default=settings.top_results, help="Number of ranked rows to print")
    p.add_argument("--details", type=int, default=5, help="Print detailed reports for top N")
    return p


def smoke_test() -> None:
    settings.validate()
    c = MassiveClient(settings.api_key, settings.base_url, settings.timeout, retries=settings.request_retries)
    print("Testing Full Market Snapshot...")
    snap = c.snapshot()
    print(f"✅ snapshot {len(snap):,} tickers")
    print("Testing ticker overview...")
    m = c.overview("AAPL")
    print(f"✅ overview {m.get('name')} type={m.get('type')} mcap={m.get('market_cap')}")
    today = datetime.now(ET).date()
    start = (today - timedelta(days=5)).isoformat()
    print("Testing daily aggregates...")
    d = c.aggs("AAPL", 1, "day", start, today.isoformat(), limit=100)
    print(f"✅ daily aggregates {len(d)} bars")
    print("Testing minute aggregates...")
    m1 = c.aggs("AAPL", 1, "minute", (today - timedelta(days=2)).isoformat(), today.isoformat(), limit=5000)
    print(f"✅ minute aggregates {len(m1)} bars")
    print("Testing news...")
    try:
        n = c.news("AAPL", 72, 3)
        print(f"✅ news {len(n)} article(s)")
    except MassiveError as exc:
        print(f"⚠️ news unavailable: {exc}")


def main() -> None:
    args = parser().parse_args()
    if args.smoke_test:
        smoke_test()
        return
    if args.demo:
        reports = demo_reports()
        diagnostics = {"mode": "demo", "reports": len(reports)}
    else:
        engine = V2Engine(settings)
        reports, diagnostics = engine.run(args.ticker.upper() if args.ticker else None)

    print_ranking(reports, args.top)
    for r in reports[: args.details]:
        print_detail(r)
    save(reports, diagnostics)
    print("\nSaved output/v2_watchlist.json, output/v2_watchlist.csv and output/reports/*.json")
