from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Snapshot:
    ticker: str
    price: float | None
    prev_close: float | None
    change_pct: float | None
    cumulative_volume: float
    minute_volume: float = 0.0
    minute_ts: int | None = None


@dataclass
class Candidate:
    ticker: str
    name: str = ""
    price: float = 0.0
    prev_close: float | None = None
    gap_pct: float = 0.0
    current_volume: float = 0.0
    snapshot_minute_ts: int | None = None
    avg_daily_volume: float | None = None
    rough_rvol: float | None = None
    dollar_volume: float = 0.0
    minute_spike_proxy: float | None = None
    market_cap: float = 0.0
    sic_code: str = ""
    sic_description: str = ""
    sector_etf: str = "SPY"
    sector_name: str = "Unknown"
    pm_volume_state: str = "UNKNOWN"
    discovered_by: list[str] = field(default_factory=list)
    pre_score: float = 0.0


@dataclass
class AnalysisReport:
    ticker: str
    name: str
    price: float
    market_cap: float
    gap_pct: float
    direction: str
    setup: str
    state: str
    score: float
    long_score: float
    short_score: float
    score_margin: float
    score_breakdown: dict[str, float]
    data_completeness_pct: float
    data_as_of_et: str | None
    discovered_by: list[str]
    pm_volume: float
    pm_volume_state: str
    runtime_rvol: float | None
    runtime_rvol_session: str | None
    recent_5m_rvol: float | None
    vwap: float | None
    distance_from_vwap_pct: float | None
    pm_high: float | None
    pm_low: float | None
    prior_pm_high: float | None
    prior_pm_low: float | None
    atr14: float | None
    market_context: dict[str, Any]
    sector_context: dict[str, Any]
    technical: dict[str, Any]
    relative_strength: dict[str, Any]
    news: dict[str, Any]
    livermore: dict[str, Any]
    levels: dict[str, Any]
    scenarios: dict[str, Any]
    next_trigger: str
    why: list[str]
    risks: list[str]
    missing: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
