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
| `uv run uvicorn api.main:app --reload` | API on http://127.0.0.1:8000 |
| `cd web && npm install && npm run dev` | Web UI on http://127.0.0.1:5173 (proxies `/api` → API) |

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
- Weekly plan default: **Sunday 6:00 PM Pacific** (use Task Scheduler + `jobs.weekly --trigger scheduled`)  
- Trades intended within **24 hours** of plan (tracked, not blocking)

## API (summary)

- `GET /dashboard`, `GET /stories`, `GET /plans/current` (includes staleness banner fields)  
- `POST /runs/daily`, `POST /runs/weekly` (requires `X-API-Key` if `HOUSEHOLD_API_KEY` set)  
- `POST /trades`, `PATCH /plans/items/{id}/decision`  
- `GET /insights/latest`, `POST /insights/generate`  

## Project layout

- `core/` — SQLite, portfolio, ledger, rules, snapshots  
- `pipeline/` — daily analysis  
- `trader_agent.py` — weekly plan per portfolio  
- `performance_agent.py` — lessons / metrics  
- `api/` — FastAPI  
- `web/` — React UI  
- `jobs/` — CLI schedulers  
- `data/` — `app.db` and exports (gitignored)

## Validation

Story URLs and tickers are checked via HTTP + yfinance (see `validation.py`).
