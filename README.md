# G-GScreener V2.1

> **V2.1 hardening release:** correctness, runtime-volume behavior, scoring integrity, caching, retries and richer diagnostics. See [`CODE_REVIEW_V2.1.md`](CODE_REVIEW_V2.1.md) for the independent review and exact changes.

Key V2.1 changes:

- current partial daily bars no longer contaminate historical indicators
- current relative strength uses current SPY/sector changes
- reaction to news now affects the score
- Runtime RVOL automatically switches from premarket (04:00) to RTH-only (09:30) after the open
- abnormal RTH volume can ARM a setup without requiring strong premarket volume
- diversified discovery across Gap Up / Gap Down / volume / dollar-volume leaders
- persistent aggregate caching + HTTP retry/backoff
- LONG and SHORT scores, score margin, data timestamp and next trigger in every report
- 10 core tests

---

A ranked U.S. stock discovery + setup engine built on **Massive Stocks Starter**.

V1.1 answered one question:

> Which stocks pass my hard filters?

V2 answers a better question:

> Which stocks deserve attention right now, why, in which direction, and what still needs confirmation?

The engine is designed as a **research/watchlist tool**, not an automatic trading system.

---

## Why V2 exists

V1.1 required both:

```text
|Gap| >= 5%
AND
Premarket Volume >= 1,000,000
```

That caused an important problem early in premarket. A stock could gap 10%–20% on a major event and disappear entirely because only 100K–200K shares had traded at 04:30 ET.

V2 changes the model:

```text
EVENT -> DISCOVER -> SCORE -> WATCH/ARMED/CONFIRMED
```

A large gap is discovered immediately. Volume affects **quality and state**, not whether the stock exists.

---

# Core eligibility

Final candidates must satisfy:

```text
Price > $5
Market Cap >= $2B
Common Stock (CS)
OTC excluded by the Massive snapshot
```

These remain hard gates because the current playbook is intended for relatively liquid, established U.S. equities rather than micro/penny stocks.

---

# Discovery engine

A ticker enters the initial candidate pool through either:

### Gap event

```text
Gap Up   >= +5%
Gap Down <= -5%
```

**No 1M-volume requirement is used for discovery.**

### Volume leader

The whole-market snapshot is also ranked by rough volume participation:

```text
current accumulated volume / 20-session average full-day volume
```

This is only a cheap first-pass mechanism. The expensive, accurate same-time RVOL calculation is performed later on shortlisted candidates.

---

# Premarket volume states

Premarket/current accumulated volume is classified instead of used as a binary reject filter:

```text
<100K        LOW
100K–250K    WATCH
250K–500K    ACTIVE
500K–1M      STRONG
>=1M         QUALIFIED
```

Example:

```text
GTLB
Gap +23%
PM Volume 103K

=> DISCOVERED
=> Volume State: WATCH
=> not deleted
```

---

# Runtime Relative Volume

V2 replaces the V1.1 RVOL concept for enriched candidates with **same-time RVOL**.

V2.1 uses session-aware same-time RVOL. During premarket it compares from 04:00 ET. After the regular session opens it automatically switches to an RTH-only comparison from 09:30 ET.

If the newest delayed bar is 10:45 ET:

```text
Today's RTH volume from 09:30 -> 10:45
--------------------------------------
Median RTH volume from 09:30 -> 10:45
across the previous 20 trading sessions
```

This means the Massive ~15-minute delay is acceptable: today and history are compared at the same clock cutoff and in the same session window.

V2 also calculates:

```text
Latest ~5-minute volume
-----------------------
Median volume during the same clock window
across previous sessions
```

So a stock can show:

```text
Runtime RVOL: 3.2x
Recent 5m RVOL: 9.7x
```

which tells us that participation has accelerated **right now** even before cumulative RVOL reaches 5x.

---

# Market context

V2 analyzes daily history of:

```text
SPY
QQQ
```

It produces a price-based regime:

```text
RISK_ON
MIXED
RISK_OFF
```

based on trend alignment against the 20 / 50 / 200-day averages.

### Important limitation

V2.1 does **not** directly ingest:

- Federal Reserve policy/rate data
- CPI/inflation data
- Treasury yields

Those are explicitly reported as missing rather than guessed.

---

# Sector context

Ticker metadata supplies SIC information. V2 maps it approximately to a liquid sector ETF, for example:

```text
Technology       XLK
Financials       XLF
Energy           XLE
Health Care      XLV
Industrials      XLI
Materials        XLB
Utilities        XLU
Real Estate      XLRE
Communication    XLC
Consumer Disc.   XLY
Consumer Staples XLP
```

The engine compares sector trend and 5/20-day performance against SPY.

This SIC mapping is deliberately described as **approximate**, not canonical GICS classification.

---

# Technical analysis

For every enriched candidate, V2 builds three timeframes.

## Weekly

Derived from daily bars:

- 10-week SMA
- 30-week SMA
- bullish / neutral / bearish trend

## Daily

- EMA 20
- SMA 20
- SMA 50
- SMA 200
- ATR 14
- 5-day return
- 20-day return
- prior 20-day high/low
- 52-week high/low
- trend classification

## 4-hour

Derived from Massive minute aggregates:

- 20-period EMA
- 50-period SMA
- trend classification

The score rewards multi-timeframe alignment rather than a single-chart signal.

---

# Intraday / premarket structure

Minute bars are used to calculate:

- session VWAP
- premarket high (PMH)
- premarket low (PML)
- prior PMH/PML excluding the newest few bars
- latest delayed price
- distance from VWAP

This supports breakout/breakdown confirmation and helps detect when a ticker is already too extended to chase.

---

# Relative Strength / Weakness

V2 compares a stock against:

```text
SPY
Sector ETF
```

over multiple windows.

For a long candidate, being stronger than both market and sector adds points.

For a short candidate, persistent relative weakness adds points.

This is **not RSI**. It is actual relative price performance.

---

# News and catalyst context

Massive ticker news is included in Stocks plans and V2 can query it for shortlisted candidates.

The current classifier identifies categories such as:

```text
EARNINGS
M&A
REGULATORY
CONTRACT
ANALYST
NEWS
```

It also reads Massive's ticker-level news sentiment when available.

V2 then compares the headline direction with price behavior and VWAP to label reaction examples such as:

```text
POSITIVE_NEWS_ACCEPTED
GOOD_NEWS_BEING_SOLD
NEGATIVE_NEWS_CONFIRMED
BAD_NEWS_BEING_BOUGHT
NEWS_PRICE_DIVERGENCE
```

The important idea is:

> The news is not enough. Price reaction to the news matters.

---

# Fundamental limitation in V2.1

The original analysis prompt calls for revenue growth, earnings growth, management guidance, analyst expectations and full financial statements.

Massive Stocks Starter does **not** include the Financials & Ratios expansion.

Therefore V2.1 does **not invent these values** and does not silently replace them with guesses.

Reports explicitly state that full fundamentals / analyst revisions / management guidance have not been independently verified.

This is a planned later enrichment layer.

---

# Livermore engine

The uploaded Hebrew edition of *Reminiscences of a Stock Operator / סוחר מניות* was reviewed while defining the V2 rules.

The code turns several recurring principles into measurable behavior:

### 1. Determine the direction of least resistance

Market, sector, weekly, daily and 4H trend alignment matter.

### 2. Wait for price to prove the thesis

A stock is not attractive simply because it appears "cheap" or "expensive".

Meaningful pivot confirmation receives substantial weight.

### 3. Prefer confirmation over anticipation

Breakout/breakdown through an important level is treated differently from a prediction that a breakout *might* occur.

### 4. Do not force activity

A candidate can remain `WATCH`. The engine is allowed to return no confirmed setup.

### 5. Add only after favorable progress

The report explicitly states that adds should occur only after the thesis has progressed and a new pivot/confirmation appears.

It does **not** recommend averaging down into an invalid thesis.

### 6. Avoid chasing

If price becomes excessively extended from VWAP, the state can become:

```text
EXTENDED
```

even when the score is otherwise high.

---

# Score — 0 to 100

Each candidate is evaluated separately for LONG and SHORT. The stronger direction becomes the displayed bias.

Current V2.1 weights:

| Component | Max |
|---|---:|
| Market regime | 10 |
| Sector | 10 |
| Weekly/Daily/4H technicals | 25 |
| Runtime/recent volume | 20 |
| Relative strength/weakness | 10 |
| Event + news | 10 |
| Livermore price confirmation | 15 |
| **Total** | **100** |

The score is a **rules-based quality ranking**, not a calibrated probability of profit.

---

# States

V2 currently uses:

```text
WATCH
ARMED
CONFIRMED
EXTENDED
```

### WATCH

Interesting event, but insufficient confirmation.

### ARMED

Good score + participation. The ticker is approaching a meaningful trigger.

### CONFIRMED

High score and the Livermore pivot-confirmation condition is satisfied.

### EXTENDED

The setup may be valid, but price is too far from VWAP under the configured threshold. Do not chase.

---

# Setups

Initial V2 setups:

```text
GAP & GO LONG
GAP & GO SHORT
PIVOT / BREAKOUT LONG
PIVOT / BREAKDOWN SHORT
MOMENTUM WATCH
```

This is intentionally a small playbook. More setups should be added only when their rules are explicit and testable.

---

# Setup levels

For ranked ideas, V2 calculates research/reference levels:

- pivot
- aggressive trigger
- conservative trigger
- stop reference
- thesis invalidation
- 1R reference target
- 2R reference target
- add reference
- when not to trade

These are deterministic research levels produced from PM structure, VWAP, ATR and daily levels. They are **not automatic broker orders**.

---

# Scenario model

Each detailed report includes directional / neutral / opposite scenarios with approximate percentages and explicit triggers.

These percentages are heuristic score-derived estimates — **not statistically calibrated probabilities**.

---

# Installation

```bash
git checkout -b feature/v2-scoring-engine
```

Copy the V2 files into the repository, then:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put your real API key only in `.env`:

```env
MASSIVE_API_KEY=YOUR_KEY
```

`.env` is ignored by Git.

---

# Smoke test

```bash
python app.py --smoke-test
```

Tests:

- full-market snapshot
- ticker overview / market cap
- daily aggregates
- minute aggregates
- ticker news

---

# Offline demo

```bash
python app.py --demo
```

This demonstrates the ranking/report format without API calls.

---

# Full-market scan

```bash
python app.py
```

The process is intentionally two-stage:

```text
13,000+ stocks
    ↓ cheap whole-market discovery
Gap events + volume leaders
    ↓ eligibility
Price / Market Cap / Common Stock
    ↓ shortlist
Top ~25 candidates
    ↓ expensive enrichment
Minute history + same-time RVOL + daily/weekly/4H + sector + news
    ↓
LONG/SHORT scoring
    ↓
Ranked ideas + setups + states
```

This avoids performing hundreds of expensive historical queries for all 13,000 tickers.

---

# Analyze one ticker

A ticker can be forced through the complete V2 pipeline even if it would not rank highly in the broad discovery pass:

```bash
python app.py --ticker GTLB
python app.py --ticker DELL
```

This is especially useful when you already noticed a stock manually.

---

# Output

```text
output/v2_watchlist.json
output/v2_watchlist.csv
output/reports/TICKER.json
```

The terminal displays a ranked table and detailed reports for the top candidates.

Example shape:

```text
#  TICKER  SCORE  BIAS   STATE      SETUP
1  XYZ      84.5  LONG   CONFIRMED  GAP & GO LONG
2  ABC      78.2  SHORT  ARMED      GAP & GO SHORT
3  DEF      69.4  LONG   WATCH      PIVOT / BREAKOUT LONG
```

---

# Useful configuration

```env
DISCOVERY_GAP_PCT=5
MAX_ENRICH_CANDIDATES=30
DOLLAR_VOLUME_TOP_N=50
GAP_UP_ENRICH_QUOTA=8
GAP_DOWN_ENRICH_QUOTA=8
VOLUME_ENRICH_QUOTA=10
ROUGH_RVOL_TOP_N=100

PM_VOLUME_WATCH=100000
PM_VOLUME_ACTIVE=250000
PM_VOLUME_STRONG=500000
PM_VOLUME_QUALIFIED=1000000

RUNTIME_RVOL_THRESHOLD=5
RUNTIME_RVOL_LOOKBACK=20
RUNTIME_RVOL_PREMARKET_START=04:00
RUNTIME_RVOL_RTH_START=09:30
RUNTIME_RVOL_ARM_THRESHOLD=2
RECENT_5M_RVOL_ARM_THRESHOLD=3

ARMED_SCORE=70
CONFIRMED_SCORE=80
EXTENDED_VWAP_PCT=6
```

---

# V2.1 intentional missing pieces

The report tells you when these are missing instead of guessing:

- direct Fed/CPI/yield macro feed
- complete company financial statements on Stocks Starter
- management guidance verification
- analyst consensus/revisions
- calibrated scenario probabilities
- Level II
- broker execution

These are later modules, not hidden assumptions.

---

# Development philosophy

```text
Discover broadly.
Rank objectively.
Wait for confirmation.
Do not force a trade.
Do not chase extension.
Let price prove the thesis.
```