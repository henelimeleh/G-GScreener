from __future__ import annotations

from datetime import datetime, time, timedelta

from .cache import BarCache, MetadataCache, average_daily_volume_map, previous_market_sessions
from .config import Settings
from .context import market_context, market_score, relative_strength, sector_context, sector_score
from .livermore import livermore_score
from .massive import MassiveClient, MassiveError
from .models import AnalysisReport, Candidate, Snapshot
from .news import classify_news
from .scoring import compose_scores
from .sector import sector_from_sic
from .setups import build_levels, choose_setup, determine_state, next_trigger_text, scenarios
from .technicals import completed_daily_bars, technical_bundle
from .utils import ET, num, pct_change, ts_to_et
from .volume import current_session_metrics, pm_volume_state, runtime_rvol


def normalize_snapshot(raw: dict) -> Snapshot | None:
    ticker = raw.get("ticker")
    if not ticker:
        return None
    minute = raw.get("min") or {}
    day = raw.get("day") or {}
    prev = raw.get("prevDay") or {}
    price = num(minute.get("c"))
    if price is None:
        price = num(day.get("c"))
    prev_close = num(prev.get("c"))
    change = num(raw.get("todaysChangePerc"))
    if change is None and price is not None and prev_close:
        change = pct_change(price, prev_close)
    volume = num(minute.get("av"))
    if volume is None:
        volume = num(day.get("v"), 0) or 0
    minute_volume = num(minute.get("v"), 0) or 0
    return Snapshot(
        ticker=str(ticker),
        price=price,
        prev_close=prev_close,
        change_pct=change,
        cumulative_volume=volume,
        minute_volume=minute_volume,
        minute_ts=int(minute.get("t")) if minute.get("t") is not None else None,
    )


def _is_snapshot_premarket(snap: Snapshot) -> bool:
    if snap.minute_ts is None:
        return False
    tt = ts_to_et(snap.minute_ts).time().replace(tzinfo=None)
    return time(4, 0) <= tt < time(9, 30)


def _minute_spike_proxy(snap: Snapshot) -> float | None:
    """Latest minute volume vs average observed minute volume since 04:00 ET.

    This is only a broad-discovery acceleration proxy. Exact historical
    same-time RVOL is still calculated after enrichment.
    """
    if snap.minute_ts is None or snap.cumulative_volume <= 0 or snap.minute_volume <= 0:
        return None
    dt = ts_to_et(snap.minute_ts)
    tt = dt.time().replace(tzinfo=None)
    if not (time(4, 0) <= tt < time(20, 0)):
        return None
    elapsed = (dt.hour * 60 + dt.minute) - (4 * 60) + 1
    if elapsed < 5:
        return None
    avg_per_minute = snap.cumulative_volume / elapsed
    if avg_per_minute <= 0:
        return None
    return snap.minute_volume / avg_per_minute


class V2Engine:
    def __init__(self, settings: Settings):
        self.s = settings
        self.s.validate()
        self.client = MassiveClient(
            settings.api_key,
            settings.base_url,
            settings.timeout,
            retries=settings.request_retries,
        )
        self.meta = MetadataCache(self.client, ttl_hours=settings.metadata_ttl_hours)
        self.bar_cache = BarCache()
        self._daily_cache: dict[str, list[dict]] = {}
        self._minute_cache: dict[str, list[dict]] = {}

    def daily_bars(self, ticker: str, days: int = 400) -> list[dict]:
        if ticker in self._daily_cache:
            return self._daily_cache[ticker]
        today = datetime.now(ET).date()
        start = (today - timedelta(days=days)).isoformat()
        end = today.isoformat()
        key = f"daily-{ticker}-{start}-{end}"
        rows = self.bar_cache.get(key, timedelta(minutes=self.s.daily_cache_ttl_minutes))
        if rows is None:
            rows = self.client.aggs(ticker, 1, "day", start, end, limit=5000)
            self.bar_cache.set(key, rows)
        self._daily_cache[ticker] = rows
        return rows

    def minute_bars(self, ticker: str, days: int = 35) -> list[dict]:
        if ticker in self._minute_cache:
            return self._minute_cache[ticker]
        today = datetime.now(ET).date()
        start = (today - timedelta(days=days)).isoformat()
        end = today.isoformat()
        key = f"minute-{ticker}-{start}-{end}"
        rows = self.bar_cache.get(key, timedelta(minutes=self.s.minute_cache_ttl_minutes))
        if rows is None:
            rows = self.client.aggs(ticker, 1, "minute", start, end, limit=50000)
            self.bar_cache.set(key, rows)
        self._minute_cache[ticker] = rows
        return rows

    def _snapshot_map(self) -> tuple[list[Snapshot], dict[str, Snapshot]]:
        raw = self.client.snapshot()
        stocks = []
        for item in raw:
            snap = normalize_snapshot(item)
            if snap:
                stocks.append(snap)
        return stocks, {x.ticker: x for x in stocks}

    @staticmethod
    def _select_diverse(candidates: list[Candidate], settings: Settings) -> list[Candidate]:
        if len(candidates) <= settings.max_enrich_candidates:
            return candidates
        chosen: list[Candidate] = []
        seen: set[str] = set()

        def take(items: list[Candidate], n: int) -> None:
            added = 0
            for c in items:
                if len(chosen) >= settings.max_enrich_candidates or added >= n:
                    break
                if c.ticker in seen:
                    continue
                chosen.append(c)
                seen.add(c.ticker)
                added += 1

        gap_up = [c for c in candidates if "GAP_UP" in c.discovered_by]
        gap_down = [c for c in candidates if "GAP_DOWN" in c.discovered_by]
        volume = [c for c in candidates if any(x in c.discovered_by for x in ("VOLUME_LEADER", "DOLLAR_VOLUME_LEADER", "MINUTE_SPIKE_PROXY"))]
        take(gap_up, settings.gap_up_quota)
        take(gap_down, settings.gap_down_quota)
        take(volume, settings.volume_quota)

        for c in candidates:
            if len(chosen) >= settings.max_enrich_candidates:
                break
            if c.ticker not in seen:
                chosen.append(c)
                seen.add(c.ticker)
        return chosen[: settings.max_enrich_candidates]

    def discover(self, specific_ticker: str | None = None) -> tuple[list[Candidate], dict, dict[str, Snapshot]]:
        now = datetime.now(ET)
        stocks, by_ticker = self._snapshot_map()
        print(f"Snapshot: {len(stocks):,} ticker(s)")

        avg_map: dict[str, float] = {}
        rough_set: set[str] = set()
        dollar_set: set[str] = set()
        spike_set: set[str] = set()

        if specific_ticker:
            ticker = specific_ticker.upper()
            if ticker not in by_ticker:
                raise RuntimeError(f"{ticker} is not present in the current Massive snapshot.")
            initial = [by_ticker[ticker]]
            print("Single-ticker mode: skipping whole-market 20-session baseline for a faster deep-dive.")
        else:
            print(f"Building {self.s.runtime_rvol_lookback}-session whole-market volume baseline...")
            sessions = previous_market_sessions(self.client, now.date(), self.s.runtime_rvol_lookback)
            avg_map = average_daily_volume_map(sessions)
            print(f"Baseline: {len(avg_map):,} ticker(s)")

            eligible_price = [x for x in stocks if x.price is not None and x.price > self.s.min_price]
            gaps = [x for x in eligible_price if x.change_pct is not None and abs(x.change_pct) >= self.s.discovery_gap_pct]

            rough_pairs = []
            dollar_pairs = []
            spike_pairs = []
            for x in eligible_price:
                avg = avg_map.get(x.ticker)
                rr = x.cumulative_volume / avg if avg and avg > 0 else 0
                if rr > 0:
                    rough_pairs.append((rr, x))
                dollar_pairs.append(((x.price or 0) * x.cumulative_volume, x))
                spike = _minute_spike_proxy(x)
                if (
                    spike is not None
                    and spike >= self.s.minute_spike_min_ratio
                    and x.cumulative_volume >= self.s.minute_spike_min_cum_volume
                ):
                    spike_pairs.append((spike, x))

            rough_pairs.sort(key=lambda z: z[0], reverse=True)
            dollar_pairs.sort(key=lambda z: z[0], reverse=True)
            spike_pairs.sort(key=lambda z: z[0], reverse=True)
            rough_stocks = [x for _, x in rough_pairs[: self.s.rough_rvol_top_n]]
            dollar_stocks = [x for _, x in dollar_pairs[: self.s.dollar_volume_top_n]]
            spike_stocks = [x for _, x in spike_pairs[: self.s.minute_spike_top_n]]
            rough_set = {x.ticker for x in rough_stocks}
            dollar_set = {x.ticker for x in dollar_stocks}
            spike_set = {x.ticker for x in spike_stocks}
            union = {x.ticker: x for x in gaps + rough_stocks + dollar_stocks + spike_stocks}
            initial = list(union.values())
            print(
                f"Discovery: {len(gaps)} gap event(s), {len(rough_stocks)} rough-volume leader(s), "
                f"{len(dollar_stocks)} dollar-volume leader(s), {len(spike_stocks)} minute-spike proxy leader(s), "
                f"{len(initial)} unique."
            )

        candidates: list[Candidate] = []
        rejected = []
        try:
            for snap in initial:
                if snap.price is None or snap.price <= self.s.min_price:
                    continue
                meta = self.meta.get(snap.ticker)
                if not bool(meta.get("active", True)) or str(meta.get("type") or "").upper() != "CS":
                    rejected.append((snap.ticker, "not active common stock"))
                    continue
                mcap = num(meta.get("market_cap"))
                if mcap is None or mcap < self.s.min_market_cap:
                    rejected.append((snap.ticker, "market cap below threshold"))
                    continue

                avg = avg_map.get(snap.ticker)
                rr = snap.cumulative_volume / avg if avg and avg > 0 else None
                state = "UNKNOWN"
                if _is_snapshot_premarket(snap):
                    state = pm_volume_state(
                        snap.cumulative_volume,
                        self.s.pm_watch,
                        self.s.pm_active,
                        self.s.pm_strong,
                        self.s.pm_qualified,
                    )

                discovered_by = []
                if specific_ticker:
                    discovered_by.append("FORCED_TICKER")
                if snap.change_pct is not None and snap.change_pct >= self.s.discovery_gap_pct:
                    discovered_by.append("GAP_UP")
                if snap.change_pct is not None and snap.change_pct <= -self.s.discovery_gap_pct:
                    discovered_by.append("GAP_DOWN")
                if snap.ticker in rough_set:
                    discovered_by.append("VOLUME_LEADER")
                if snap.ticker in dollar_set:
                    discovered_by.append("DOLLAR_VOLUME_LEADER")
                spike_proxy = _minute_spike_proxy(snap)
                if snap.ticker in spike_set:
                    discovered_by.append("MINUTE_SPIKE_PROXY")

                etf, sector_name = sector_from_sic(meta.get("sic_code"), meta.get("sic_description", ""))
                pre = min(abs(snap.change_pct or 0) * 1.6, 35)
                if snap.ticker in rough_set:
                    pre += min((rr or 0) * 12, 25)
                if snap.ticker in dollar_set:
                    pre += 5
                if snap.ticker in spike_set and spike_proxy is not None:
                    pre += min(spike_proxy * 1.5, 10)
                if state != "UNKNOWN":
                    pre += {"LOW": 0, "WATCH": 4, "ACTIVE": 7, "STRONG": 10, "QUALIFIED": 14}[state]
                if mcap >= 10e9:
                    pre += 5
                elif mcap >= 5e9:
                    pre += 3
                else:
                    pre += 1

                candidates.append(Candidate(
                    ticker=snap.ticker,
                    name=str(meta.get("name") or ""),
                    price=float(snap.price),
                    prev_close=snap.prev_close,
                    gap_pct=float(snap.change_pct or 0),
                    current_volume=float(snap.cumulative_volume),
                    snapshot_minute_ts=snap.minute_ts,
                    avg_daily_volume=avg,
                    rough_rvol=rr,
                    dollar_volume=float((snap.price or 0) * snap.cumulative_volume),
                    minute_spike_proxy=spike_proxy,
                    market_cap=float(mcap),
                    sic_code=str(meta.get("sic_code") or ""),
                    sic_description=str(meta.get("sic_description") or ""),
                    sector_etf=etf,
                    sector_name=sector_name,
                    pm_volume_state=state,
                    discovered_by=discovered_by,
                    pre_score=round(pre, 1),
                ))
        finally:
            self.meta.flush()

        candidates.sort(key=lambda x: x.pre_score, reverse=True)
        if not specific_ticker:
            candidates = self._select_diverse(candidates, self.s)
        diagnostics = {
            "rejected": rejected,
            "initial_count": len(initial),
            "enrich_count": len(candidates),
            "selection": "diversified quotas across gap-up, gap-down and volume leaders",
        }
        return candidates, diagnostics, by_ticker

    def _news(self, ticker: str) -> tuple[dict, bool]:
        if not self.s.enable_news:
            return {"available": False, "catalyst": "DISABLED", "sentiment": "UNKNOWN", "score": 0, "headlines": []}, False
        try:
            rows = self.client.news(ticker, self.s.news_lookback_hours)
            return classify_news(rows, ticker), True
        except MassiveError as exc:
            return {"available": False, "catalyst": "UNAVAILABLE", "sentiment": "UNKNOWN", "score": 0, "headlines": [], "error": str(exc)}, False

    @staticmethod
    def _news_reaction(news: dict, gap_pct: float, direction: str, price: float, vwap: float | None) -> str:
        sentiment = news.get("sentiment")
        correct_side = None if not vwap else ((direction == "LONG" and price >= vwap) or (direction == "SHORT" and price <= vwap))
        if sentiment == "POSITIVE" and gap_pct > 0:
            return "POSITIVE_NEWS_ACCEPTED" if correct_side is not False else "GOOD_NEWS_BEING_SOLD"
        if sentiment == "NEGATIVE" and gap_pct < 0:
            return "NEGATIVE_NEWS_CONFIRMED" if correct_side is not False else "BAD_NEWS_BEING_BOUGHT"
        if sentiment in {"POSITIVE", "NEGATIVE"}:
            return "NEWS_PRICE_DIVERGENCE"
        return "UNCLEAR"

    def analyze_candidate(
        self,
        c: Candidate,
        market_ctx: dict,
        spy_daily: list[dict],
        sector_daily_cache: dict[str, list[dict]],
        snapshot_map: dict[str, Snapshot],
    ) -> AnalysisReport:
        now = datetime.now(ET)
        print(f"  enriching {c.ticker} ...", flush=True)
        missing = [
            "Direct macro inputs (Fed rate, CPI/inflation, Treasury yields) are not available from this Stocks-only data source.",
            "Analyst consensus/estimate revisions and management guidance are not independently verified in V2.1.",
            "Full financial statements are not scored because Massive Stocks Starter does not include the Financials & Ratios expansion.",
        ]

        try:
            minute = self.minute_bars(c.ticker)
        except MassiveError as exc:
            minute = []
            missing.append(f"Minute bars unavailable: {exc}")

        session = current_session_metrics(minute, now.date())
        analysis_price = session.get("last_price") or c.price
        aligned_gap = pct_change(analysis_price, c.prev_close) if c.prev_close else c.gap_pct
        if aligned_gap is None:
            aligned_gap = c.gap_pct

        try:
            daily = self.daily_bars(c.ticker)
        except MassiveError as exc:
            daily = []
            missing.append(f"Daily history unavailable: {exc}")

        tech = technical_bundle(daily, minute, analysis_price, now.date())
        vinfo = runtime_rvol(
            minute,
            now.date(),
            self.s.runtime_rvol_premarket_start,
            self.s.runtime_rvol_rth_start,
            self.s.runtime_rvol_lookback,
        )

        actual_pm_volume = session.get("pm_volume")
        if actual_pm_volume is None or actual_pm_volume <= 0:
            actual_pm_volume = c.current_volume if _is_snapshot_premarket(Snapshot(c.ticker, c.price, c.prev_close, c.gap_pct, c.current_volume, 0.0, c.snapshot_minute_ts)) else 0
        actual_pm_state = pm_volume_state(
            actual_pm_volume,
            self.s.pm_watch,
            self.s.pm_active,
            self.s.pm_strong,
            self.s.pm_qualified,
        )
        vinfo["pm_state"] = actual_pm_state

        if c.sector_etf not in sector_daily_cache:
            try:
                sector_daily_cache[c.sector_etf] = self.daily_bars(c.sector_etf)
            except MassiveError as exc:
                sector_daily_cache[c.sector_etf] = []
                missing.append(f"Sector ETF history unavailable for {c.sector_etf}: {exc}")
        sec_bars = sector_daily_cache[c.sector_etf]

        spy_snap = snapshot_map.get("SPY")
        sec_snap = snapshot_map.get(c.sector_etf)
        spy_current = spy_snap.change_pct if spy_snap else None
        sec_current = sec_snap.change_pct if sec_snap else None

        sec_ctx = sector_context(
            c.sector_etf,
            completed_daily_bars(sec_bars, now.date()),
            completed_daily_bars(spy_daily, now.date()),
            etf_current_change=sec_current,
            spy_current_change=spy_current,
        )

        stock_d = tech.get("daily", {})
        spy_d = market_ctx.get("spy", {})
        sec_d = sec_ctx.get("metrics", {})
        rs = relative_strength(stock_d, spy_d, sec_d, aligned_gap, spy_current, sec_current)
        base_news, news_ok = self._news(c.ticker)
        if not news_ok:
            missing.append("Ticker news endpoint was unavailable/disabled, so catalyst analysis is incomplete.")

        directional = {}
        for direction in ("LONG", "SHORT"):
            ms = market_score(market_ctx, direction)
            ss = sector_score(sec_ctx, direction)
            liv_score, liv = livermore_score(
                direction,
                analysis_price,
                tech,
                session,
                vinfo,
                ms,
                ss,
                self.s.extended_vwap_pct,
            )
            direction_news = dict(base_news)
            direction_news["reaction"] = self._news_reaction(direction_news, aligned_gap, direction, analysis_price, session.get("vwap"))
            scores = compose_scores(direction, analysis_price, aligned_gap, market_ctx, sec_ctx, tech, vinfo, rs, direction_news, liv_score)
            directional[direction] = (scores, liv, direction_news)

        direction = max(directional, key=lambda d: directional[d][0]["total"])
        scores, liv, news = directional[direction]
        long_score = directional["LONG"][0]["total"]
        short_score = directional["SHORT"][0]["total"]
        score_margin = abs(long_score - short_score)

        setup = choose_setup(direction, aligned_gap, tech, analysis_price)
        levels = build_levels(direction, analysis_price, tech, session)
        state = determine_state(
            scores["total"],
            direction,
            analysis_price,
            aligned_gap,
            session,
            liv,
            actual_pm_state,
            vinfo,
            self.s.armed_score,
            self.s.confirmed_score,
            self.s.extended_vwap_pct,
            self.s.runtime_arm_threshold,
            self.s.recent_5m_arm_threshold,
        )

        vwap = session.get("vwap")
        dist = (analysis_price / vwap - 1) * 100 if vwap else None
        why = []
        if aligned_gap >= self.s.discovery_gap_pct:
            why.append(f"Gap Up {aligned_gap:+.2f}% triggered discovery")
        elif aligned_gap <= -self.s.discovery_gap_pct:
            why.append(f"Gap Down {aligned_gap:+.2f}% triggered discovery")
        if c.discovered_by:
            why.append("Discovery channels: " + ", ".join(c.discovered_by))
        if actual_pm_state != "LOW" or actual_pm_volume > 0:
            why.append(f"Premarket participation: {actual_pm_state} ({actual_pm_volume:,.0f} shares)")
        if vinfo.get("runtime_rvol") is not None:
            why.append(f"{vinfo.get('session_name')} same-time RVOL {vinfo['runtime_rvol']:.1f}x")
        if vinfo.get("recent_5m_rvol") is not None and vinfo["recent_5m_rvol"] >= 2:
            why.append(f"Recent 5m volume {vinfo['recent_5m_rvol']:.1f}x normal")
        why.append(
            f"Weekly/Daily/4H: {tech.get('weekly',{}).get('trend')}/"
            f"{tech.get('daily',{}).get('trend')}/{tech.get('four_hour',{}).get('trend')}"
        )
        if news.get("catalyst") not in {"NONE_FOUND", "UNAVAILABLE", "DISABLED"}:
            why.append(f"Recent catalyst: {news.get('catalyst')} ({news.get('sentiment')}); reaction={news.get('reaction')}")
        if liv.get("pivot_confirmed"):
            why.append("Livermore price-confirmation rule: pivot is confirmed")

        risks = list(liv.get("warnings", []))
        if actual_pm_state in {"LOW", "WATCH"} and abs(aligned_gap) >= self.s.discovery_gap_pct:
            risks.append(f"Premarket volume is not yet strong ({actual_pm_volume:,.0f}; state={actual_pm_state})")
        if direction == "LONG" and aligned_gap < -5:
            risks.append("Chosen long bias fights a large Gap Down; treat as reversal-watch only")
        if direction == "SHORT" and aligned_gap > 5:
            risks.append("Chosen short bias fights a large Gap Up; treat as failed-gap watch only")
        if score_margin < 8:
            risks.append(f"Long/short score separation is small ({score_margin:.1f} points); directional conviction is limited")

        checks = {
            "minute": bool(minute),
            "daily": bool(daily),
            "market": bool(market_ctx.get("available")),
            "sector": bool(sec_ctx.get("available")),
            "news": news_ok,
            "runtime_rvol": vinfo.get("runtime_rvol") is not None,
        }
        weights = {"minute": 20, "daily": 25, "market": 15, "sector": 15, "news": 15, "runtime_rvol": 10}
        completeness = sum(weights[k] for k, ok in checks.items() if ok)

        cutoff_ts = session.get("last_ts") or c.snapshot_minute_ts
        data_as_of = ts_to_et(int(cutoff_ts)).strftime("%Y-%m-%d %H:%M ET") if cutoff_ts else None

        return AnalysisReport(
            ticker=c.ticker,
            name=c.name,
            price=analysis_price,
            market_cap=c.market_cap,
            gap_pct=float(aligned_gap),
            direction=direction,
            setup=setup,
            state=state,
            score=scores["total"],
            long_score=long_score,
            short_score=short_score,
            score_margin=score_margin,
            score_breakdown={k: v for k, v in scores.items() if k != "total"},
            data_completeness_pct=float(completeness),
            data_as_of_et=data_as_of,
            discovered_by=c.discovered_by,
            pm_volume=actual_pm_volume,
            pm_volume_state=actual_pm_state,
            runtime_rvol=vinfo.get("runtime_rvol"),
            runtime_rvol_session=vinfo.get("session_name"),
            recent_5m_rvol=vinfo.get("recent_5m_rvol"),
            vwap=vwap,
            distance_from_vwap_pct=dist,
            pm_high=session.get("pm_high"),
            pm_low=session.get("pm_low"),
            prior_pm_high=session.get("prior_pm_high"),
            prior_pm_low=session.get("prior_pm_low"),
            atr14=tech.get("daily", {}).get("atr14"),
            market_context=market_ctx,
            sector_context={"name": c.sector_name, **sec_ctx},
            technical=tech,
            relative_strength=rs,
            news=news,
            livermore=liv,
            levels=levels,
            scenarios=scenarios(direction, levels, scores["total"]),
            next_trigger=next_trigger_text(state, direction, levels, liv),
            why=why,
            risks=risks,
            missing=missing,
        )

    def run(self, specific_ticker: str | None = None) -> tuple[list[AnalysisReport], dict]:
        print("Fetching full-market snapshot...")
        candidates, diagnostics, snapshot_map = self.discover(specific_ticker)
        if not candidates:
            return [], diagnostics

        print(f"Enriching {len(candidates)} candidate(s) with minute/daily/news context...")
        try:
            spy_daily_raw = self.daily_bars("SPY")
        except MassiveError as exc:
            print(f"WARNING SPY daily unavailable: {exc}")
            spy_daily_raw = []
        try:
            qqq_daily_raw = self.daily_bars("QQQ")
        except MassiveError as exc:
            print(f"WARNING QQQ daily unavailable: {exc}")
            qqq_daily_raw = []

        now = datetime.now(ET)
        spy_daily = completed_daily_bars(spy_daily_raw, now.date())
        qqq_daily = completed_daily_bars(qqq_daily_raw, now.date())
        spy_snap = snapshot_map.get("SPY")
        qqq_snap = snapshot_map.get("QQQ")
        mctx = market_context(
            spy_daily,
            qqq_daily,
            spy_current_change=spy_snap.change_pct if spy_snap else None,
            qqq_current_change=qqq_snap.change_pct if qqq_snap else None,
        )
        sector_cache: dict[str, list[dict]] = {"SPY": spy_daily_raw}

        reports = []
        for c in candidates:
            try:
                reports.append(self.analyze_candidate(c, mctx, spy_daily_raw, sector_cache, snapshot_map))
            except Exception as exc:
                # One malformed ticker/data response should not kill the market scan.
                print(f"  WARNING {c.ticker}: unexpected analysis failure: {exc}")

        reports.sort(key=lambda r: (r.score, r.score_margin), reverse=True)
        diagnostics["market_regime"] = mctx.get("regime")
        diagnostics["reports"] = len(reports)
        diagnostics["above_min_idea_score"] = sum(r.score >= self.s.min_idea_score for r in reports)
        return reports, diagnostics
