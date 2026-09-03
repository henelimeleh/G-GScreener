from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import AnalysisReport
from .utils import compact

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"


def fmt(v, digits=2):
    return "N/A" if v is None else f"{v:.{digits}f}"


def print_ranking(reports: list[AnalysisReport], top: int) -> None:
    print("\n" + "=" * 126)
    print("G-GSCREENER V2.1 — RANKED MARKET IDEAS")
    print("=" * 126)
    if not reports:
        print("No candidates survived discovery + eligibility.")
        return
    print(
        f"{'#':>2} {'TICKER':<7} {'SCORE':>6} {'L/S':>11} {'BIAS':<6} {'STATE':<10} "
        f"{'SETUP':<24} {'GAP':>8} {'PM VOL':>9} {'RVOL':>8} {'5M':>7} {'AS OF':>13}"
    )
    for i, r in enumerate(reports[:top], 1):
        rr = f"{r.runtime_rvol:.1f}x" if r.runtime_rvol is not None else "N/A"
        r5 = f"{r.recent_5m_rvol:.1f}x" if r.recent_5m_rvol is not None else "N/A"
        ls = f"{r.long_score:.0f}/{r.short_score:.0f}"
        asof = (r.data_as_of_et or "N/A").split()[-2] if r.data_as_of_et else "N/A"
        print(
            f"{i:>2} {r.ticker:<7} {r.score:>6.1f} {ls:>11} {r.direction:<6} {r.state:<10} "
            f"{r.setup:<24} {r.gap_pct:>+7.2f}% {compact(r.pm_volume):>9} {rr:>8} {r5:>7} {asof:>13}"
        )


def print_detail(r: AnalysisReport) -> None:
    print("\n" + "─" * 108)
    print(f"{r.ticker} — {r.name} | SCORE {r.score:.1f}/100 | {r.direction} | {r.state} | {r.setup}")
    print("─" * 108)
    print(f"Data as of: {r.data_as_of_et or 'N/A'} | Quant completeness: {r.data_completeness_pct:.0f}%")
    print(
        f"Price ${r.price:.2f} | MCAP ${compact(r.market_cap)} | Gap {r.gap_pct:+.2f}% | "
        f"PM Vol {compact(r.pm_volume)} [{r.pm_volume_state}]"
    )
    print(
        f"Runtime RVOL ({r.runtime_rvol_session or 'N/A'}) {fmt(r.runtime_rvol,1)}x | "
        f"Last 5m {fmt(r.recent_5m_rvol,1)}x | VWAP {('$'+fmt(r.vwap)) if r.vwap else 'N/A'} | "
        f"Dist VWAP {fmt(r.distance_from_vwap_pct)}%"
    )
    print(f"Directional scores: LONG={r.long_score:.1f} | SHORT={r.short_score:.1f} | margin={r.score_margin:.1f}")
    print("Scores: " + " | ".join(f"{k}={v:.1f}" for k, v in r.score_breakdown.items()))
    print(f"Market: {r.market_context.get('regime')} | Sector: {r.sector_context.get('name')} / {r.sector_context.get('etf')} ({r.sector_context.get('trend')})")
    t = r.technical
    print(f"Trends: Weekly={t.get('weekly',{}).get('trend')} | Daily={t.get('daily',{}).get('trend')} | 4H={t.get('four_hour',{}).get('trend')}")
    print(f"Catalyst: {r.news.get('catalyst')} | News sentiment: {r.news.get('sentiment')} | Reaction: {r.news.get('reaction')}")
    print(f"NEXT TRIGGER: {r.next_trigger}")
    print("WHY:")
    for x in r.why:
        print(f"  ✅ {x}")
    if r.risks:
        print("RISKS:")
        for x in r.risks:
            print(f"  ⚠️  {x}")
    print("SETUP LEVELS (research triggers, not automatic orders):")
    for key in ("pivot", "aggressive_trigger", "conservative_trigger", "stop_reference", "invalidation", "target_1r", "target_2r", "add_reference"):
        v = r.levels.get(key)
        if v is not None:
            print(f"  {key}: ${v:.2f}")
    for key in ("aggressive_rule", "conservative_rule", "add_rule", "do_not_trade_if"):
        if r.levels.get(key):
            print(f"  {key}: {r.levels[key]}")
    print("LIVERMORE:")
    print(f"  pivot_confirmed={r.livermore.get('pivot_confirmed')} | timeframes_aligned={r.livermore.get('timeframes_aligned')}")
    print(f"  {r.livermore.get('book_principle')}")
    print(f"  {r.livermore.get('add_rule')}")
    print("MISSING / NOT VERIFIED:")
    for x in r.missing:
        print(f"  • {x}")


def save(reports: list[AnalysisReport], diagnostics: dict) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "reports").mkdir(parents=True, exist_ok=True)
    payload = {"diagnostics": diagnostics, "reports": [r.as_dict() for r in reports]}
    (OUTPUT / "v2_watchlist.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    fields = [
        "ticker", "score", "long_score", "short_score", "score_margin", "direction", "state", "setup",
        "price", "market_cap", "gap_pct", "pm_volume", "pm_volume_state", "runtime_rvol",
        "runtime_rvol_session", "recent_5m_rvol", "vwap", "data_as_of_et", "data_completeness_pct",
    ]
    with (OUTPUT / "v2_watchlist.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        for r in reports:
            d = r.as_dict()
            wr.writerow({k: d.get(k) for k in fields})

    for r in reports:
        (OUTPUT / "reports" / f"{r.ticker}.json").write_text(json.dumps(r.as_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
