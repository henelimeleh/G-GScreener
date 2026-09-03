from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass(frozen=True)
class Settings:
    base_url: str = os.getenv("MASSIVE_BASE_URL", "https://api.massive.com").rstrip("/")
    timeout: int = int(os.getenv("MASSIVE_TIMEOUT_SECONDS", "30"))
    request_retries: int = int(os.getenv("MASSIVE_REQUEST_RETRIES", "3"))

    min_price: float = float(os.getenv("MIN_PRICE", "5"))
    min_market_cap: float = float(os.getenv("MIN_MARKET_CAP", "2000000000"))

    discovery_gap_pct: float = float(os.getenv("DISCOVERY_GAP_PCT", "5"))
    max_enrich_candidates: int = int(os.getenv("MAX_ENRICH_CANDIDATES", "30"))
    rough_rvol_top_n: int = int(os.getenv("ROUGH_RVOL_TOP_N", "100"))
    dollar_volume_top_n: int = int(os.getenv("DOLLAR_VOLUME_TOP_N", "50"))
    minute_spike_top_n: int = int(os.getenv("MINUTE_SPIKE_TOP_N", "50"))
    minute_spike_min_ratio: float = float(os.getenv("MINUTE_SPIKE_MIN_RATIO", "3"))
    minute_spike_min_cum_volume: int = int(os.getenv("MINUTE_SPIKE_MIN_CUM_VOLUME", "100000"))
    gap_up_quota: int = int(os.getenv("GAP_UP_ENRICH_QUOTA", "8"))
    gap_down_quota: int = int(os.getenv("GAP_DOWN_ENRICH_QUOTA", "8"))
    volume_quota: int = int(os.getenv("VOLUME_ENRICH_QUOTA", "10"))

    pm_watch: int = int(os.getenv("PM_VOLUME_WATCH", "100000"))
    pm_active: int = int(os.getenv("PM_VOLUME_ACTIVE", "250000"))
    pm_strong: int = int(os.getenv("PM_VOLUME_STRONG", "500000"))
    pm_qualified: int = int(os.getenv("PM_VOLUME_QUALIFIED", "1000000"))

    runtime_rvol_threshold: float = float(os.getenv("RUNTIME_RVOL_THRESHOLD", "5"))
    runtime_rvol_lookback: int = int(os.getenv("RUNTIME_RVOL_LOOKBACK", "20"))
    runtime_rvol_premarket_start: str = os.getenv("RUNTIME_RVOL_PREMARKET_START", "04:00")
    runtime_rvol_rth_start: str = os.getenv("RUNTIME_RVOL_RTH_START", "09:30")
    runtime_arm_threshold: float = float(os.getenv("RUNTIME_RVOL_ARM_THRESHOLD", "2"))
    recent_5m_arm_threshold: float = float(os.getenv("RECENT_5M_RVOL_ARM_THRESHOLD", "3"))

    min_idea_score: float = float(os.getenv("MIN_IDEA_SCORE", "55"))
    armed_score: float = float(os.getenv("ARMED_SCORE", "70"))
    confirmed_score: float = float(os.getenv("CONFIRMED_SCORE", "80"))
    extended_vwap_pct: float = float(os.getenv("EXTENDED_VWAP_PCT", "6"))

    news_lookback_hours: int = int(os.getenv("NEWS_LOOKBACK_HOURS", "72"))
    enable_news: bool = _bool("ENABLE_NEWS", True)
    top_results: int = int(os.getenv("TOP_RESULTS", "10"))

    metadata_ttl_hours: int = int(os.getenv("METADATA_CACHE_TTL_HOURS", "168"))
    daily_cache_ttl_minutes: int = int(os.getenv("DAILY_CACHE_TTL_MINUTES", "360"))
    minute_cache_ttl_minutes: int = int(os.getenv("MINUTE_CACHE_TTL_MINUTES", "10"))

    @property
    def api_key(self) -> str:
        value = os.getenv("MASSIVE_API_KEY", "").strip()
        if not value or value == "PUT_YOUR_MASSIVE_API_KEY_HERE":
            raise RuntimeError("MASSIVE_API_KEY missing. Copy .env.example to .env and set the key.")
        return value

    def validate(self) -> None:
        if self.min_price <= 0:
            raise ValueError("MIN_PRICE must be > 0")
        if self.min_market_cap < 0:
            raise ValueError("MIN_MARKET_CAP must be >= 0")
        if self.discovery_gap_pct <= 0:
            raise ValueError("DISCOVERY_GAP_PCT must be > 0")
        if not (0 <= self.pm_watch <= self.pm_active <= self.pm_strong <= self.pm_qualified):
            raise ValueError("PM volume thresholds must satisfy WATCH <= ACTIVE <= STRONG <= QUALIFIED")
        if self.runtime_rvol_lookback < 5:
            raise ValueError("RUNTIME_RVOL_LOOKBACK should be at least 5 sessions")
        if self.max_enrich_candidates <= 0:
            raise ValueError("MAX_ENRICH_CANDIDATES must be > 0")
        if not (0 <= self.armed_score <= self.confirmed_score <= 100):
            raise ValueError("Scoring thresholds must satisfy 0 <= ARMED_SCORE <= CONFIRMED_SCORE <= 100")


settings = Settings()
