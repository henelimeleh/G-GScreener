from __future__ import annotations

from .context import market_score, sector_score, relative_strength_score
from .technicals import technical_direction_score
from .volume import volume_score


def event_news_score(gap_pct: float, direction: str, news: dict) -> float:
    score = 0.0
    mag = abs(gap_pct)
    gap_direction_matches = (direction == "LONG" and gap_pct > 0) or (direction == "SHORT" and gap_pct < 0)
    reaction = news.get("reaction")

    # Large event magnitude only receives full credit in its natural direction.
    if mag >= 15:
        mag_score = 4
    elif mag >= 10:
        mag_score = 3
    elif mag >= 5:
        mag_score = 2
    elif mag >= 3:
        mag_score = 1
    else:
        mag_score = 0
    score += mag_score if gap_direction_matches else mag_score * 0.25

    score += float(news.get("score", 0)) * 0.55
    sentiment = news.get("sentiment")
    if direction == "LONG" and sentiment == "POSITIVE":
        score += 1
    if direction == "SHORT" and sentiment == "NEGATIVE":
        score += 1
    if direction == "LONG" and sentiment == "NEGATIVE":
        score -= 1
    if direction == "SHORT" and sentiment == "POSITIVE":
        score -= 1

    # Reaction to news is part of the actual score in V2.1, rather than merely
    # being printed after scoring as it was in V2.0.
    aligned_reactions = {
        "LONG": {"POSITIVE_NEWS_ACCEPTED", "BAD_NEWS_BEING_BOUGHT"},
        "SHORT": {"NEGATIVE_NEWS_CONFIRMED", "GOOD_NEWS_BEING_SOLD"},
    }
    adverse_reactions = {
        "LONG": {"GOOD_NEWS_BEING_SOLD", "NEGATIVE_NEWS_CONFIRMED"},
        "SHORT": {"BAD_NEWS_BEING_BOUGHT", "POSITIVE_NEWS_ACCEPTED"},
    }
    if reaction in aligned_reactions[direction]:
        score += 2
    elif reaction in adverse_reactions[direction]:
        score -= 2
    elif reaction == "NEWS_PRICE_DIVERGENCE":
        score -= 0.5

    return round(max(0, min(10, score)), 1)


def compose_scores(direction: str, price: float, gap_pct: float, market_ctx: dict, sector_ctx: dict, technical: dict, vol: dict, rs: dict, news: dict, livermore_score_value: float) -> dict:
    values = {
        "market": market_score(market_ctx, direction),
        "sector": sector_score(sector_ctx, direction),
        "technical": technical_direction_score(technical, direction, price),
        "volume": volume_score(vol.get("runtime_rvol"), vol.get("recent_5m_rvol"), vol.get("pm_state", "LOW")),
        "relative_strength": relative_strength_score(rs, direction),
        "event_news": event_news_score(gap_pct, direction, news),
        "livermore": livermore_score_value,
    }
    values["total"] = round(sum(values.values()), 1)
    return values
