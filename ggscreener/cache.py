from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .massive import MassiveClient
from .utils import num

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


class MetadataCache:
    """Ticker metadata cache with batched disk flushes.

    V2.0 rewrote the entire metadata JSON file after every ticker lookup. During a
    first broad scan that can mean dozens of redundant writes. V2.1 keeps changes
    in memory and flushes once after discovery (or explicitly when requested).
    """

    def __init__(self, client: MassiveClient, ttl_hours: int = 168):
        self.client = client
        self.path = CACHE / "metadata.json"
        self.data = load_json(self.path, {})
        self.ttl = timedelta(hours=ttl_hours)
        self.dirty = False

    def get(self, ticker: str) -> dict:
        now = datetime.now(timezone.utc)
        item = self.data.get(ticker)
        if item:
            try:
                fetched = datetime.fromisoformat(item["fetched_at"])
                if now - fetched < self.ttl:
                    return item["data"]
            except Exception:
                pass

        raw = self.client.overview(ticker)
        self.data[ticker] = {"fetched_at": now.isoformat(), "data": raw}
        self.dirty = True
        return raw

    def flush(self) -> None:
        if self.dirty:
            save_json(self.path, self.data)
            self.dirty = False


class BarCache:
    """Short-lived persistent cache for aggregate bars.

    Massive Starter data is delayed anyway, so repeatedly downloading the same
    35-day minute history every time the script is run is wasteful. This cache
    keeps recent aggregate responses for a configurable TTL.
    """

    def __init__(self):
        self.directory = CACHE / "bars"

    @staticmethod
    def _safe_key(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)

    def path_for(self, key: str) -> Path:
        return self.directory / f"{self._safe_key(key)}.json"

    def get(self, key: str, ttl: timedelta):
        path = self.path_for(key)
        payload = load_json(path, None)
        if not isinstance(payload, dict):
            return None
        fetched_at = payload.get("fetched_at")
        try:
            fetched = datetime.fromisoformat(fetched_at)
        except Exception:
            return None
        if datetime.now(timezone.utc) - fetched > ttl:
            return None
        rows = payload.get("rows")
        return rows if isinstance(rows, list) else None

    def set(self, key: str, rows: list[dict]) -> None:
        save_json(
            self.path_for(key),
            {"fetched_at": datetime.now(timezone.utc).isoformat(), "rows": rows},
        )


def previous_market_sessions(client: MassiveClient, before: date, count: int) -> list[list[dict]]:
    directory = CACHE / "grouped_daily"
    result: list[list[dict]] = []
    offset = 1
    while len(result) < count and offset <= 50:
        d = before - timedelta(days=offset)
        offset += 1
        if d.weekday() >= 5:
            continue
        path = directory / f"{d.isoformat()}.json"
        rows = load_json(path, None)
        if rows is None:
            rows = client.grouped_day(d.isoformat())
            save_json(path, rows)
        if rows:
            result.append(rows)
    if len(result) < count:
        raise RuntimeError(f"Could only obtain {len(result)} trading sessions; need {count}.")
    return result


def average_daily_volume_map(sessions: list[list[dict]]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for rows in sessions:
        for row in rows:
            ticker = row.get("T")
            volume = num(row.get("v"))
            if ticker and volume is not None and volume >= 0:
                values[str(ticker)].append(volume)
    return {k: sum(v) / len(v) for k, v in values.items() if v}
