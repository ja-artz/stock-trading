"""Seed household, session, portfolio, and initial snapshot."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

load_dotenv()

from core.seed import ensure_seeded
from core.db import db_session


def seed() -> None:
    ensure_seeded()
    with db_session() as conn:
        row = conn.execute("SELECT id FROM portfolios LIMIT 1").fetchone()
        print(f"Household ready. portfolio_id={row['id'] if row else 'n/a'}")


if __name__ == "__main__":
    seed()
