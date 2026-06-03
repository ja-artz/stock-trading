# stock-trading

Household paper-trading platform: daily news analysis (three risk personas), weekly trader plans per portfolio, manual Sofi trade logging, and insights.

## Setup

1. Install [uv](https://docs.astral.sh/uv/) and sync:

```bash
uv sync --no-install-project
```

2. Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and optionally `HOUSEHOLD_API_KEY`.

3. Seed the database (one shared $1,000 portfolio):

```bash
uv run python scripts/seed_household.py
```

## Commands

| Command | Description |
|---------|-------------|
| `uv run python main.py` | Daily news + analyst pipeline (persists to SQLite) |
| `uv run python -m jobs.daily` | Same as daily job |
| `uv run python -m jobs.weekly` | Weekly trader plan per active portfolio |
| `uv run python scripts/run_backtest.py` | 90-day historical backtest (see below) |
| `uv run uvicorn api.main:app --reload` | API on http://127.0.0.1:8000 |
| `cd web && npm install && npm run dev` | Web UI (Figma Make design) on http://127.0.0.1:5173 — proxies `/api` → API |

### Web UI (P1 screens)

- **Home** — NAV, run daily analysis / generate trading plan, quick links  
- **Stories** — latest analysis with headline / upside tabs  
- **Trading plan** (`/recommendations`) — on-demand recommendations, staleness banner, accept/reject/defer, **trader agent chat** (discuss / revise with confirm-before-apply)  
- **Global chat** — floating badge on all pages (drawer); story and plan-item focus from detail views  
- **Portfolio** — positions + log trade (Sofi)  
- **Insights** — generate lessons report  
- **Settings** — API key + trading rules  

Not in P1 UI: watchlist, alerts, search, multi-portfolio tabs, attribution history (mock-only in Figma).

### Set starting state (Settings)

- **Apply $X cash only** — uncommitted book (default $1,000)
- **Reset to cash** — clears logged trades
- **Import CSV** — `ticker,quantity,avg_cost,instrument_type` plus free cash in the form

### Docker (optional)

```bash
docker compose up --build
```

SQLite lives at `./data/app.db` (bind-mounted). No separate database container.

## Trading rules (default)

- Max **33%** of NAV per position  
- Max **5** new positions per week (Pacific, week starts Monday)  
- **10%** cash floor  
- Max **2** open option positions  
- Options and shorts allowed  
- Optional scheduled plan: **Sunday 6:00 PM Pacific** (`jobs/weekly.py --trigger scheduled`) — plans are otherwise generated on demand  
- Trades intended within **24 hours** of plan (tracked, not blocking)

## API (summary)

- `GET /dashboard`, `GET /stories`, `GET /plans/current` (includes staleness banner fields)  
- `POST /runs/daily` (requires `X-API-Key` if `HOUSEHOLD_API_KEY` set). Add `?stream=1` for **SSE progress** (used by the web UI).
- `POST /runs/trading-plan` or `POST /runs/weekly` — generate trading plan (on-demand; may return **no changes** if analysis unchanged since last plan). Add `?stream=1` for **SSE progress**.  
- `POST /trades`, `PATCH /plans/items/{id}/decision`  
- `GET /insights/latest`, `POST /insights/generate`  
- `POST /chat/threads`, `GET /chat/threads`, `GET /chat/threads/{id}/messages`, `POST /chat/threads/{id}/messages`  
- `POST /chat/plan-revisions/preview`, `POST /chat/plan-revisions/apply` (requires API key if `HOUSEHOLD_API_KEY` set)  

## Project layout

- `core/` — SQLite, portfolio, ledger, rules, snapshots  
- `pipeline/` — daily analysis  
- `trader_agent.py` — on-demand trading plan per portfolio (knows time since last plan; may recommend no changes)  
- `trader_chat_agent.py` — multi-turn chat with plan revision proposals  
- `core/trader_context.py` — shared context for plan generation and chat  
- `performance_agent.py` — lessons / metrics  
- `api/` — FastAPI  
- `web/` — React UI  
- `jobs/` — CLI schedulers  
- `data/` — `app.db` and exports (gitignored)

## Validation

Story URLs and tickers are checked via HTTP + yfinance (see `validation.py`).

## Backtest (pre-live capital)

CLI only. Weekly flow matches production: **news → analysts (3 personas) → trader agent → paper book** (all trader plan items treated as accepted).

Default: **13 weekly runs** ending `2026-06-01`. Output: `weekly_portfolio` in JSON + terminal table.

```bash
# Full run (cached under data/backtest/cache/{news,runs,plans}/)
uv run python scripts/run_backtest.py

# You already have analysis in cache/runs/ — only run trader + P&L (~13 LLM calls)
uv run python scripts/run_backtest.py --trader-only

# Recompute P&L from cache/runs/ + cache/plans/ (no LLM)
uv run python scripts/run_backtest.py --skip-trader
```

News default query is `news` (see `backtest/config.py`). Live app uses general top-stories RSS; historical days require Google search + `after:`/`before:`.

Legacy daily mode (moderate persona only, no trader): `--daily --persona-direct`
