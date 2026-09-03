# G-GScreener V2.1 — Independent Code Review & Hardening

V2.1 is a correctness/performance pass over V2.0. It does not change the core philosophy: broad discovery first, expensive analysis only for shortlisted names, and price confirmation before a setup becomes actionable.

## High-impact issues found in V2.0

1. **Current partial daily candle could contaminate historical indicators.** Moving averages, ATR and "previous day" levels were calculated from data requested through today. V2.1 explicitly removes the in-progress current-day daily bar and injects current price separately.
2. **Current relative strength used a rough proxy.** The stock's current change was compared with SPY's average 5-day return/day. V2.1 compares current stock change with current SPY and sector ETF snapshot changes.
3. **News reaction was printed but not scored.** V2.1 calculates reaction before scoring and rewards/penalizes direction based on whether good/bad news is accepted or rejected by price.
4. **RTH volume setups were constrained by premarket participation state.** V2.1 can move to ARMED/CONFIRMED from same-time Runtime RVOL / recent 5m participation even with low PM volume.
5. **Runtime RVOL always started at 04:00.** V2.1 automatically uses 04:00 during premarket and switches to 09:30 RTH-only after the opening bell.
6. **Discovery could be crowded by one signal family.** V2.1 reserves shortlist capacity for Gap Up, Gap Down and volume leaders, and adds dollar-volume leaders.
7. **Every candidate with an ADV value was labeled VOLUME_LEADER.** V2.1 only assigns the label to tickers that actually landed in the rough-volume leader set.
8. **Premarket state could be incorrectly inferred from total day volume after 09:30.** V2.1 leaves snapshot PM state UNKNOWN outside premarket and calculates true PM volume only during enrichment from minute bars.
9. **Missing data could earn neutral points.** UNKNOWN technical/market/RS data now contributes zero rather than free neutral score.
10. **Broad runtime anomaly discovery relied only on full-day ADV progress.** V2.1 adds a zero-extra-call latest-minute acceleration proxy (`min.v` versus the stock's average observed minute volume so far) to surface sudden activity before exact historical RVOL enrichment.
11. **A single API failure could drop the entire candidate.** Minute/daily/sector/news data degrade independently where possible; missing fields are reported instead of silently guessed.

## Efficiency improvements

- HTTP retry/backoff for 429/5xx/network instability.
- Batched metadata cache writes instead of rewriting metadata.json after every lookup.
- Persistent short-TTL minute/daily aggregate cache.
- Single-ticker analysis skips the whole-market 20-session baseline.
- In-memory aggregate caches within a run.
- Diversified enrichment shortlist reduces wasted expensive requests.
- Snapshot-level minute-spike proxy catches sudden volume acceleration without historical API calls for all 13,000 tickers.

## Output improvements

Every report now exposes:

- data timestamp (`data_as_of_et`)
- LONG score
- SHORT score
- directional score margin
- discovery channels
- Runtime RVOL session (`PREMARKET` or `RTH`)
- explicit next trigger
- quant-data completeness percentage
- scenario probabilities clearly labeled `HEURISTIC_NOT_CALIBRATED`

## Setup improvements

Static conservative prices are explicitly documented as reference levels, not blind entries. The preferred conservative behavior is still a 5-minute close through the pivot plus hold/retest. Adding is permitted only after favorable progress and renewed confirmation.

## Tests

V2.1 expands the core suite from 4 to 11 tests, including:

- Massive Starter snapshot fields
- PM volume state
- SIC sector mapping
- current-price breakout setup logic
- automatic PM -> RTH same-time RVOL switch
- incomplete-day daily-bar exclusion
- UNKNOWN trend behavior
- real current relative strength
- news-reaction scoring
- RTH volume-driven ARMED state
