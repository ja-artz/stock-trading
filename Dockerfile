FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY config.py news_collector.py retrieval_agent.py analysis_agent.py validation.py ./
COPY core ./core
COPY pipeline ./pipeline
COPY api ./api
COPY jobs ./jobs
COPY scripts ./scripts
COPY trader_agent.py performance_agent.py main.py ./

RUN uv sync --no-install-project

ENV DATABASE_URL=sqlite:///./data/app.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
