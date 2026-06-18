"""SQLite database connection and schema."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional
import config

_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS households (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'America/Los_Angeles',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    display_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    rules_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS portfolios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    name TEXT NOT NULL,
    initial_cash REAL NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS portfolio_rules (
    portfolio_id INTEGER PRIMARY KEY REFERENCES portfolios(id),
    rules_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    run_at TEXT NOT NULL,
    run_type TEXT NOT NULL DEFAULT 'daily',
    status TEXT NOT NULL DEFAULT 'completed',
    payload_json TEXT,
    export_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS weekly_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
    analysis_run_id INTEGER REFERENCES analysis_runs(id),
    plan_at TEXT NOT NULL,
    based_on_analysis_at TEXT NOT NULL,
    trigger_type TEXT NOT NULL DEFAULT 'manual',
    summary TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weekly_plan_id INTEGER NOT NULL REFERENCES weekly_plans(id),
    priority INTEGER NOT NULL DEFAULT 1,
    action TEXT NOT NULL,
    ticker TEXT,
    instrument_type TEXT,
    horizon TEXT,
    size_hint TEXT,
    suggested_notional_usd REAL,
    suggested_quantity REAL,
    quantity_unit TEXT,
    pct_nav REAL,
    pct_cash REAL,
    pct_position REAL,
    sizing_summary TEXT,
    detail_json TEXT,
    persona_consensus TEXT,
    rationale TEXT,
    rule_warnings TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_item_id INTEGER NOT NULL REFERENCES plan_items(id),
    member_id INTEGER NOT NULL REFERENCES members(id),
    decision TEXT NOT NULL,
    note TEXT,
    decided_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ledger_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
    event_type TEXT NOT NULL DEFAULT 'trade',
    side TEXT NOT NULL,
    ticker TEXT NOT NULL,
    instrument_type TEXT NOT NULL DEFAULT 'stock',
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    fees REAL NOT NULL DEFAULT 0,
    strike REAL,
    expiry TEXT,
    plan_item_id INTEGER REFERENCES plan_items(id),
    member_id INTEGER REFERENCES members(id),
    logged_at TEXT NOT NULL,
    executed_within_24h INTEGER,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
    as_of TEXT NOT NULL,
    cash_usd REAL NOT NULL,
    positions_json TEXT NOT NULL DEFAULT '[]',
    nav_usd REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    portfolio_id INTEGER REFERENCES portfolios(id),
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    detail_json TEXT,
    occurred_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS insight_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    portfolio_id INTEGER REFERENCES portfolios(id),
    report_type TEXT NOT NULL DEFAULT 'lessons',
    period_start TEXT,
    period_end TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_chat_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id),
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
    weekly_plan_id INTEGER REFERENCES weekly_plans(id),
    title TEXT,
    focus_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER NOT NULL REFERENCES agent_chat_threads(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_revision_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id INTEGER REFERENCES agent_chat_threads(id),
    weekly_plan_id INTEGER NOT NULL REFERENCES weekly_plans(id),
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
    revision_json TEXT NOT NULL,
    preview_json TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at TEXT
);
"""


def resolve_db_path() -> Path:
    url = config.DATABASE_URL
    if url.startswith("sqlite:///"):
        raw = url.replace("sqlite:///", "", 1)
        if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
            return Path(raw)
        return Path(raw.lstrip("./"))
    raise ValueError(f"Unsupported DATABASE_URL: {url}")


def ensure_data_dir() -> Path:
    path = resolve_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    db_path = ensure_data_dir()
    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_session() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


_PLAN_ITEM_SIZING_COLUMNS = (
    ("suggested_notional_usd", "REAL"),
    ("suggested_quantity", "REAL"),
    ("quantity_unit", "TEXT"),
    ("pct_nav", "REAL"),
    ("pct_cash", "REAL"),
    ("pct_position", "REAL"),
    ("sizing_summary", "TEXT"),
    ("detail_json", "TEXT"),
)

_PLAN_ITEM_TIER_COLUMNS = (
    ("capital_tier", "INTEGER"),
    ("conviction_grade", "TEXT"),
    ("sector", "TEXT"),
    ("theme_tag", "TEXT"),
    ("correlation_group", "TEXT"),
)

_TIER_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS position_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
    ledger_event_id INTEGER NOT NULL DEFAULT 0,
    plan_item_id INTEGER REFERENCES plan_items(id),
    ticker TEXT NOT NULL,
    instrument_type TEXT NOT NULL DEFAULT 'stock',
    capital_tier INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    entry_price REAL NOT NULL,
    quantity_remaining REAL NOT NULL,
    forced_exit_date TEXT,
    partial_exits_json TEXT NOT NULL DEFAULT '[]',
    thesis_status TEXT NOT NULL DEFAULT 'active',
    stop_loss_pct REAL,
    breakeven_stop_active INTEGER NOT NULL DEFAULT 0,
    sector TEXT,
    theme_tag TEXT,
    correlation_group TEXT,
    expiry TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS action_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
    position_lot_id INTEGER REFERENCES position_lots(id),
    plan_item_id INTEGER REFERENCES plan_items(id),
    generated_at TEXT NOT NULL,
    priority TEXT NOT NULL,
    action TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    detail_json TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    overridden_at TEXT,
    override_note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tier_transfer_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id INTEGER NOT NULL REFERENCES portfolios(id),
    source_tier INTEGER,
    dest_tier INTEGER,
    amount_usd REAL,
    reason_code TEXT,
    action_item_id INTEGER REFERENCES action_items(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS benchmark_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    close_usd REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(symbol, as_of_date)
);
"""


def _migrate_plan_item_sizing(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(plan_items)").fetchall()}
    for name, col_type in _PLAN_ITEM_SIZING_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE plan_items ADD COLUMN {name} {col_type}")


def _migrate_plan_item_tier_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(plan_items)").fetchall()}
    for name, col_type in _PLAN_ITEM_TIER_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE plan_items ADD COLUMN {name} {col_type}")


def _migrate_tier_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(_TIER_TABLES_SQL)


def _migrate_benchmark_snapshots(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            as_of_date TEXT NOT NULL,
            close_usd REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(symbol, as_of_date)
        )
        """
    )


def init_db() -> None:
    with db_session() as conn:
        conn.executescript(_SCHEMA)
        _migrate_plan_item_sizing(conn)
        _migrate_plan_item_tier_columns(conn)
        _migrate_tier_tables(conn)
        _migrate_benchmark_snapshots(conn)


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    return dict(row)
