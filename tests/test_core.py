from datetime import date, datetime
from zoneinfo import ZoneInfo

from ggscreener.context import relative_strength, relative_strength_score
from ggscreener.engine import _minute_spike_proxy, normalize_snapshot
from ggscreener.news import classify_news
from ggscreener.scoring import event_news_score
from ggscreener.sector import sector_from_sic
from ggscreener.setups import choose_setup, determine_state
from ggscreener.technicals import completed_daily_bars, trend_label
from ggscreener.volume import pm_volume_state, runtime_rvol

ET = ZoneInfo("America/New_York")


def ms(y, m, d, hh, mm):
    return int(datetime(y, m, d, hh, mm, tzinfo=ET).timestamp() * 1000)


def test_snapshot_uses_massive_starter_fields():
    s = normalize_snapshot({
        "ticker": "GTLB",
        "todaysChangePerc": 23.3,
        "min": {"c": 55.6, "av": 103793, "t": 1788337920000},
        "prevDay": {"c": 45.09},
        "day": {"v": 0},
    })
    assert s.ticker == "GTLB"
    assert s.price == 55.6
    assert s.cumulative_volume == 103793
    assert s.change_pct == 23.3


def test_pm_volume_is_state_not_hard_gate():
    assert pm_volume_state(103793, 100000, 250000, 500000, 1000000) == "WATCH"
    assert pm_volume_state(1100000, 100000, 250000, 500000, 1000000) == "QUALIFIED"


def test_sector_mapping_software():
    etf, name = sector_from_sic("7372", "PREPACKAGED SOFTWARE")
    assert etf == "XLK"
    assert name == "Technology"


def test_gap_setup_uses_current_price_for_breakout():
    technical = {"daily": {"prior20_high": 50, "prior20_low": 40, "close": 45}}
    assert choose_setup("LONG", 9.0, technical, 55) == "GAP & GO LONG"
    assert choose_setup("SHORT", -8.0, technical, 35) == "GAP & GO SHORT"
    assert choose_setup("LONG", 1.0, technical, 51) == "PIVOT / BREAKOUT LONG"


def test_runtime_rvol_switches_to_rth_after_open():
    bars = []
    # Historical day: 100 shares at 09:30 and 100 at 09:31.
    for d in (29, 30):
        bars.extend([
            {"t": ms(2026, 8, d, 9, 30), "v": 100},
            {"t": ms(2026, 8, d, 9, 31), "v": 100},
        ])
    # Today: 1000 + 1000. Also add huge PM volume that must not contaminate RTH RVOL.
    bars.extend([
        {"t": ms(2026, 9, 1, 8, 0), "v": 50000},
        {"t": ms(2026, 9, 1, 9, 30), "v": 1000},
        {"t": ms(2026, 9, 1, 9, 31), "v": 1000},
    ])
    out = runtime_rvol(bars, date(2026, 9, 1), "04:00", "09:30", 20)
    assert out["session_name"] == "RTH"
    assert out["runtime_rvol"] == 10


def test_unknown_technical_trend_is_not_neutral_credit():
    assert trend_label(100, None, None) == "UNKNOWN"


def test_completed_daily_removes_current_partial_bar():
    rows = [
        {"t": ms(2026, 8, 31, 16, 0), "c": 100},
        {"t": ms(2026, 9, 1, 12, 0), "c": 120},
    ]
    done = completed_daily_bars(rows, date(2026, 9, 1))
    assert len(done) == 1
    assert done[0]["c"] == 100


def test_current_relative_strength_uses_current_benchmark_change():
    rs = relative_strength({}, {}, {}, 10.0, 1.0, 2.0)
    assert rs["current_vs_spy"] == 9.0
    assert rs["current_vs_sector"] == 8.0
    assert relative_strength_score(rs, "LONG") > relative_strength_score(rs, "SHORT")


def test_news_reaction_can_change_directional_score():
    news = {"score": 6, "sentiment": "POSITIVE", "reaction": "GOOD_NEWS_BEING_SOLD"}
    long_score = event_news_score(10, "LONG", news)
    short_score = event_news_score(10, "SHORT", news)
    assert short_score > 0
    assert long_score < 10


def test_state_can_arm_on_runtime_volume_without_strong_pm_volume():
    session = {"vwap": 100}
    liv = {"pivot_confirmed": False}
    state = determine_state(
        75, "LONG", 101, 1, session, liv, "LOW",
        {"runtime_rvol": 3.0, "recent_5m_rvol": 4.0},
        70, 80, 6, 2, 3,
    )
    assert state == "ARMED"


def test_snapshot_minute_spike_proxy_detects_acceleration():
    s = normalize_snapshot({
        "ticker": "XYZ",
        "todaysChangePerc": 1.0,
        "min": {"c": 20, "av": 120000, "v": 12000, "t": ms(2026, 9, 1, 5, 0)},
        "prevDay": {"c": 19.8},
    })
    proxy = _minute_spike_proxy(s)
    assert proxy is not None
    assert proxy > 5
