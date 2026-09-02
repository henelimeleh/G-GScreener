# Gap & Go Watchlist V1.1

V1.1 adds a separate **Gap Down + Premarket Volume** watchlist.

The scanner is a watchlist generator only. It does not produce entries,
stops, buy/sell signals, or execute trades.

## Global gate

Every final result must be:

- Common Stock (`type=CS`)
- Price > $5
- Market Cap >= $2B
- Non-OTC snapshot universe

## Category 1 — GAP UP + PM VOLUME

- Gap >= +5%
- Premarket cumulative volume >= 1,000,000

## Category 2 — GAP DOWN + PM VOLUME

- Gap <= -5%
- Premarket cumulative volume >= 1,000,000

## Category 3 — RELATIVE VOLUME

- Current cumulative volume / average full-day volume over prior 20 sessions >= 5x

V1.1 deliberately keeps the existing RVOL formula unchanged. A later version
can replace it with same-time/runtime RVOL without mixing that larger change
into this Gap Down release.

## Massive Starter fields

The working Starter implementation uses:

- `todaysChangePerc` for change vs previous close
- `min.c` for latest available delayed minute close
- `min.av` for today's accumulated volume

## Install

```bash
mkdir -p ~/Projects
unzip ~/Downloads/gap-go-watchlist-v1.1.zip -d ~/Projects
cd ~/Projects/gap-go-watchlist-v1.1

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
vim .env
```

Put your Massive key in `.env`.

## Test

```bash
python app.py --demo
python app.py --smoke-test
```

## Run

```bash
python app.py
```

Output:
- `output/watchlist.json`
- `output/watchlist.csv`
