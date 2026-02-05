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
- `retrieval_agent.py` - LLM agent that selects top 3 news stories
- `analysis_agent.py` - LLM agent that analyzes stories and generates recommendations
- `main.py` - Main orchestration script
- `config.py` - Configuration settings
