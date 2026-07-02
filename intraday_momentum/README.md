# Intraday Momentum Research Framework

Isolated research package for testing intraday momentum continuation strategies. **Not coupled** to the main household trading app (`core/`, `pipeline/`, `api/`).

## Prototype limitations

- **yfinance** provides ~7 calendar days of 1-minute bars per pull; run daily ingest to build a permanent archive in SQLite.
- Universe is a curated ticker list — not survivorship-safe.
- Spreads are modeled (5 bps half-spread + 5 bps slippage per side), not from NBBO.
- Results are **PROTOTYPE — not validation-grade**. Do not claim edge from this data alone.

## Setup

```bash
uv sync --extra intraday
```

## CLI

```bash
# One-time bootstrap (last 7 days)
uv run python -m intraday_momentum.cli ingest --bootstrap

# Daily incremental ingest (run after market close)
uv run python -m intraday_momentum.cli ingest

# Backfill gap (dates still in yfinance window)
uv run python -m intraday_momentum.cli ingest --from 2026-06-25 --to 2026-07-01

# Coverage report
uv run python -m intraday_momentum.cli coverage

# Show today's top movers (live)
uv run python -m intraday_momentum.cli universe --refresh

# Full archive backtest
uv run python -m intraday_momentum.cli backtest

# At 2x costs
uv run python -m intraday_momentum.cli backtest --cost-multiplier 2.0

# Single-day verdict
uv run python -m intraday_momentum.cli daily --date 2026-07-01

# Live scan (anytime before entry cutoff)
uv run python -m intraday_momentum.cli scan
```

## Daily automation

After US market close (~5:00–5:30 PM ET):

```powershell
cd "C:\Users\artzj\AI Projects\stock-trading"
uv run python -m intraday_momentum.jobs.daily_ingest
uv run python -m intraday_momentum.cli daily
```

Windows Task Scheduler: point at `uv run python -m intraday_momentum.jobs.daily_ingest`.

## Configuration

Edit [`config/strategy.yaml`](config/strategy.yaml):

- **`universe.source`** — `day_gainers` (default; like Googling "biggest movers today")
- **`universe.top_n`** — how many top movers to evaluate per scan (default 50)
- **`universe.min_percent_change`** — minimum % move to include in mover list
- **`universe.*` filters** — price, market cap, ADV applied to mover quotes
- **`execution.max_positions`** — how many positions to take per day
- **`execution.scan_times`** — discrete scan windows (your timezone)
- **`execution.entry_cutoff`** — no new entries after this time
- **`trigger.*`** — move threshold, RVOL, gap discipline
- **`labels.*`** — profit target, stop, optional `exit_velocity_threshold` (session close is implicit EOD exit)
- **`trigger.slope_window_min`** — lookback for entry ranking and velocity exits (default 15 minutes)

Optional [`config/universe.yaml`](config/universe.yaml): `include` / `exclude` overrides only.

## Data

Stored in `data/intraday_momentum/research.db` (separate from `data/app.db`).

## Tests

```bash
uv run pytest intraday_momentum/tests/
```

## Architecture

```
ingest → SQLite archive → scan-window backtest → daily WIN/LOSS verdict
```

Scan workflow mirrors manual trading: check movers at configured times (default 6:35 / 6:50 PDT), take top `max_positions` candidates, no new entries after 7:30 PDT cutoff.

Future merge with main app: [`signal_api.py`](signal_api.py) exposes the same trigger path used in backtest.
