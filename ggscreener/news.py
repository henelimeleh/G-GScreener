from __future__ import annotations

from datetime import datetime, timezone

KEYWORDS = {
    "EARNINGS": ["earnings", "quarter", "revenue", "eps", "guidance", "results", "profit"],
    "M&A": ["acquisition", "acquire", "merger", "buyout", "takeover"],
    "REGULATORY": ["fda", "approval", "approved", "regulatory", "trial", "phase 3", "phase iii"],
    "CONTRACT": ["contract", "partnership", "deal", "agreement", "award"],
    "ANALYST": ["upgrade", "downgrade", "price target", "initiates", "rating"],
}

CATEGORY_BASE = {
    "EARNINGS": 6.0,
    "REGULATORY": 6.0,
    "M&A": 5.5,
    "CONTRACT": 5.0,
    "ANALYST": 3.5,
    "NEWS": 2.0,
}


def _age_hours(value: str | None) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600)
    except Exception:
        return None


def classify_news(rows: list[dict], ticker: str) -> dict:
    if not rows:
        return {
            "available": True,
            "catalyst": "NONE_FOUND",
            "sentiment": "UNKNOWN",
            "score": 0.0,
            "confidence": "LOW",
            "headlines": [],
        }

    weighted_hits = {k: 0.0 for k in KEYWORDS}
    sentiment_values = []
    headlines = []

    for row in rows:
        title = str(row.get("title") or "")
        desc = str(row.get("description") or "")
        text = (title + " " + desc).lower()
        age = _age_hours(row.get("published_utc"))
        # Fresh catalysts matter more. Unknown timestamp remains neutral weight.
        recency_weight = 1.0 if age is None else 1.5 if age <= 12 else 1.2 if age <= 24 else 1.0 if age <= 48 else 0.7
        headlines.append({
            "title": title,
            "published_utc": row.get("published_utc"),
            "url": row.get("article_url"),
            "age_hours": round(age, 1) if age is not None else None,
        })
        for category, words in KEYWORDS.items():
            if any(word in text for word in words):
                weighted_hits[category] += recency_weight
        for insight in row.get("insights") or []:
            if str(insight.get("ticker", "")).upper() == ticker.upper():
                s = str(insight.get("sentiment") or "").lower()
                if s == "positive":
                    sentiment_values.append(1)
                elif s == "negative":
                    sentiment_values.append(-1)
                elif s == "neutral":
                    sentiment_values.append(0)

    max_hit = max(weighted_hits.values(), default=0)
    catalyst = max(weighted_hits, key=weighted_hits.get) if max_hit > 0 else "NEWS"
    sentiment_num = sum(sentiment_values) / len(sentiment_values) if sentiment_values else 0
    sentiment = "POSITIVE" if sentiment_num > 0.2 else "NEGATIVE" if sentiment_num < -0.2 else "NEUTRAL"
    base = CATEGORY_BASE.get(catalyst, 0.0)
    if sentiment in {"POSITIVE", "NEGATIVE"}:
        base += 1.5

    confidence = "HIGH" if max_hit >= 2.0 else "MEDIUM" if max_hit >= 1.0 else "LOW"
    return {
        "available": True,
        "catalyst": catalyst,
        "sentiment": sentiment,
        "score": min(base, 8.0),
        "confidence": confidence,
        "headlines": headlines[:5],
    }
