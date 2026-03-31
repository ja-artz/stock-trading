# stock-trading

This is software that is designed to enable a simple strategy for recommending stock trades based on current events.

## Setup

1. Install `uv` if you haven't already:
```bash
# On macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# On Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or via pip
pip install uv
```

2. Install dependencies with uv:
```bash
# Option 1: Install dependencies only (recommended for script projects)
uv sync --no-install-project

# Option 2: Full sync (if the above doesn't work, try this)
uv sync
```

3. Configure your IDE to use the virtual environment:
   - **VS Code/Cursor**: Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac), type "Python: Select Interpreter", and choose the `.venv` Python interpreter
   - The `pyrightconfig.json` file should help the linter find the packages automatically

4. (Optional) Set up Jupyter kernel for notebooks:
```bash
# After running uv sync, install the kernel
uv run python -m ipykernel install --user --name=stock-trading --display-name "Python (stock-trading)"
```

4. Copy `.env.example` to `.env` and add your API keys:
```bash
cp .env.example .env
```

5. Edit `.env` and add your:
   - `ANTHROPIC_API_KEY`
   - `OPENAI_API_KEY`

## Usage

Run the main script:
```bash
# Using uv (recommended)
uv run python main.py

# Or activate the virtual environment first
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate  # On Windows
python main.py
```

### Pipeline (Current)

The runtime pipeline is:

1. Collect fresh general news from Google News RSS.
2. Run two retrieval passes:
   - `headline` retrieval: major market-moving stories.
   - `upside` retrieval: non-front-page stories with asymmetric potential.
3. Each retrieval pass returns 3-5 stories.
4. Merge and deduplicate the combined candidate pool.
5. Run actionability triage to select the most actionable stories.
6. For each story: fetch persona-neutral `shared_context`, then run three analyst profiles (`aggressive`, `moderate`, `minimal_risk`) with separate JSON briefs (including `portfolio_actions`).
7. Validate article URLs and ticker symbols (see **Validation** below); optionally send failed tickers back through the analysis model once to correct recommendations.
8. Print formatted output and save `recommendations_*.json`.

### Validation

The pipeline checks that story links respond over HTTP and that equity tickers used in the analysis JSON resolve via **yfinance** (no extra API keys). Results are stored under each story’s `validation` field in the output JSON.

**Future improvement:** swap or supplement this with a dedicated market-data or exchange API (and optionally a news cross-check API) once you add API keys. Update `validation.py` and `config.py` when you do, and document new env vars here.

### Configuration Knobs

Key config values in `config.py`:

- `RETRIEVAL_MIN_STORIES_PER_AGENT` (default `3`)
- `RETRIEVAL_MAX_STORIES_PER_AGENT` (default `5`)
- `ACTIONABLE_STORIES_TO_ANALYZE` (default `5`)
- `ANALYST_PROFILES` (tuple of profile ids used for multi-persona analysis)
- `VALIDATION_URL_TIMEOUT` (seconds for HTTP checks on article URLs)
- `ENABLE_TICKER_REFINEMENT_LOOP` (when True, one extra LLM pass to fix invalid tickers)

## Jupyter Notebooks

To use Jupyter notebooks for development:

1. After installing dependencies, register the kernel:
```bash
uv run python -m ipykernel install --user --name=stock-trading --display-name "Python (stock-trading)"
```

2. Launch Jupyter:
```bash
uv run jupyter notebook
# or
uv run jupyter lab
```

3. When creating a new notebook, select "Python (stock-trading)" as the kernel.

## Project Structure

- `news_collector.py` - Collects news from Google News
- `retrieval_agent.py` - Dual-mode retrieval agent (`headline` + `upside`), each selecting 3-5 candidate stories
- `analysis_agent.py` - Actionability triage + shared context + three-persona recommendation briefs per story + optional ticker refinement
- `validation.py` - HTTP URL check + yfinance ticker validation (no paid API keys)
- `main.py` - Main orchestration script
- `config.py` - Configuration settings
- `ARCHITECTURE.md` - Mermaid architecture diagram and component notes
