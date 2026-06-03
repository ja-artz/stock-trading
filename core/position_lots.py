"""Position lot metadata linked to ledger opens."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, List, Optional

from core.db import db_session, row_to_dict
from core.portfolio import compute_nav
from core.rules import is_option_instrument, pacific_week_start
from core.tier_engine import forced_exit_date_for_tier, normalize_capital_tier


def _today_iso() -> str:
    return date.today().isoformat()


def _lot_from_row(row: Any) -> dict:
    d = row_to_dict(row) or {}
    if d.get("partial_exits_json") and isinstance(d["partial_exits_json"], str):
        try:
            d["partial_exits_list"] = json.loads(d["partial_exits_json"])
        except json.JSONDecodeError:
            d["partial_exits_list"] = []
    return d


def get_open_lots(portfolio_id: int) -> List[dict]:
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT * FROM position_lots
            WHERE portfolio_id = ? AND quantity_remaining > 1e-9
            ORDER BY entry_date, id
            """,
            (portfolio_id,),
        ).fetchall()
    return [_lot_from_row(r) for r in rows]


def count_tier1_opens_this_month(portfolio_id: int, as_of: Optional[datetime] = None) -> int:
    ref = as_of or datetime.now(timezone.utc)
    week_start = pacific_week_start(ref)
    month_start = week_start.replace(day=1) if week_start.day <= 7 else week_start
    # Pacific month boundary: first day of local month
    tz = week_start.tzinfo
    local = ref.astimezone(tz) if ref.tzinfo else ref.replace(tzinfo=timezone.utc).astimezone(tz)
    month_start = datetime(local.year, local.month, 1, tzinfo=tz)
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS c FROM position_lots
            WHERE portfolio_id = ? AND capital_tier = 1
              AND entry_date >= ?
            """,
            (portfolio_id, month_start.date().isoformat()),
        ).fetchone()
    return int(row["c"] or 0)


def enrich_lots_with_marks(portfolio_id: int, lots: List[dict]) -> List[dict]:
    nav = compute_nav(portfolio_id)
    pos_by_key = {}
    for p in nav["positions"]:
        key = f"{p['ticker']}:{p.get('instrument_type', 'stock')}"
        pos_by_key[key] = p

    out = []
    for lot in lots:
        key = f"{lot['ticker']}:{lot.get('instrument_type', 'stock')}"
        pos = pos_by_key.get(key)
        enriched = dict(lot)
        if pos:
            enriched["mark_price"] = pos.get("mark_price")
            enriched["market_value"] = pos.get("market_value")
            enriched["expiry"] = enriched.get("expiry") or pos.get("expiry")
        else:
            qty = float(lot.get("quantity_remaining") or 0)
            ep = float(lot.get("entry_price") or 0)
            enriched["mark_price"] = ep
            enriched["market_value"] = qty * ep
        out.append(enriched)
    return out


def create_lot_from_buy(
    portfolio_id: int,
    ledger_event_id: int,
    *,
    ticker: str,
    instrument_type: str,
    quantity: float,
    price: float,
    plan_item_id: Optional[int] = None,
    expiry: Optional[str] = None,
    capital_tier: Optional[int] = None,
    sector: Optional[str] = None,
    theme_tag: Optional[str] = None,
    correlation_group: Optional[str] = None,
    entry_date: Optional[str] = None,
) -> int:
    tier = normalize_capital_tier(capital_tier)
    sector_val = sector
    theme_val = theme_tag
    corr = correlation_group

    if plan_item_id:
        from core.plan_execution import get_plan_item

        item = get_plan_item(plan_item_id)
        if item:
            tier = tier or normalize_capital_tier(item.get("capital_tier"))
            detail = item
            sector_val = sector_val or item.get("sector")
            theme_val = theme_val or item.get("theme_tag")
            corr = corr or item.get("correlation_group") or item.get("ticker")

    if tier is None:
        tier = 2

    ed = _parse_entry(entry_date) or date.today()
    forced = forced_exit_date_for_tier(tier, ed)

    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO position_lots
            (portfolio_id, ledger_event_id, plan_item_id, ticker, instrument_type,
             capital_tier, entry_date, entry_price, quantity_remaining, forced_exit_date,
             partial_exits_json, thesis_status, sector, theme_tag, correlation_group, expiry)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', 'active', ?, ?, ?, ?)
            """,
            (
                portfolio_id,
                ledger_event_id,
                plan_item_id,
                ticker.upper(),
                instrument_type,
                tier,
                ed.isoformat(),
                price,
                quantity,
                forced,
                sector_val,
                theme_val,
                corr.upper() if corr else ticker.upper(),
                expiry,
            ),
        )
        return int(cur.lastrowid)


def reduce_lot_on_sell(
    portfolio_id: int,
    ticker: str,
    instrument_type: str,
    quantity_sold: float,
) -> None:
    remaining = quantity_sold
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT id, quantity_remaining FROM position_lots
            WHERE portfolio_id = ? AND ticker = ? AND instrument_type = ?
              AND quantity_remaining > 1e-9
            ORDER BY entry_date, id
            """,
            (portfolio_id, ticker.upper(), instrument_type),
        ).fetchall()
        for row in rows:
            if remaining <= 1e-9:
                break
            lot_id = row["id"]
            q = float(row["quantity_remaining"])
            take = min(q, remaining)
            new_q = q - take
            conn.execute(
                "UPDATE position_lots SET quantity_remaining = ? WHERE id = ?",
                (new_q, lot_id),
            )
            remaining -= take


def record_partial_exit(lot_id: int, reason_code: str) -> None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT partial_exits_json FROM position_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
        if not row:
            return
        try:
            fired = json.loads(row["partial_exits_json"] or "[]")
        except json.JSONDecodeError:
            fired = []
        if reason_code not in fired:
            fired.append(reason_code)
        conn.execute(
            "UPDATE position_lots SET partial_exits_json = ? WHERE id = ?",
            (json.dumps(fired), lot_id),
        )


def assign_lot_tier(
    lot_id: int,
    capital_tier: int,
    *,
    sector: Optional[str] = None,
    theme_tag: Optional[str] = None,
) -> None:
    tier = normalize_capital_tier(capital_tier) or 2
    with db_session() as conn:
        row = conn.execute(
            "SELECT entry_date FROM position_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
        forced = None
        if row:
            ed = _parse_entry(row["entry_date"])
            if ed:
                forced = forced_exit_date_for_tier(tier, ed)
        conn.execute(
            """
            UPDATE position_lots
            SET capital_tier = ?, forced_exit_date = ?,
                sector = COALESCE(?, sector), theme_tag = COALESCE(?, theme_tag)
            WHERE id = ?
            """,
            (tier, forced, sector, theme_tag, lot_id),
        )


def set_lot_thesis_status(lot_id: int, status: str) -> None:
    with db_session() as conn:
        conn.execute(
            "UPDATE position_lots SET thesis_status = ? WHERE id = ?",
            (status.strip().lower(), lot_id),
        )


def get_unmapped_positions(portfolio_id: int) -> List[dict]:
    """Holdings in ledger without open position_lots rows."""
    nav = compute_nav(portfolio_id)
    lots = get_open_lots(portfolio_id)
    lot_keys = {(l["ticker"], l.get("instrument_type", "stock")) for l in lots}
    unmapped = []
    for p in nav["positions"]:
        key = (p["ticker"], p.get("instrument_type", "stock"))
        if key not in lot_keys:
            unmapped.append(p)
    return unmapped


def backfill_lot_from_holding(
    portfolio_id: int,
    ticker: str,
    instrument_type: str,
    capital_tier: int,
    entry_date: Optional[str] = None,
    entry_price: Optional[float] = None,
    sector: Optional[str] = None,
) -> int:
    nav = compute_nav(portfolio_id)
    pos = next(
        (
            p
            for p in nav["positions"]
            if p["ticker"].upper() == ticker.upper()
            and (p.get("instrument_type") or "stock") == instrument_type
        ),
        None,
    )
    if not pos:
        raise ValueError("No open position for ticker")
    with db_session() as conn:
        cur = conn.execute(
            """
            INSERT INTO position_lots
            (portfolio_id, ledger_event_id, plan_item_id, ticker, instrument_type,
             capital_tier, entry_date, entry_price, quantity_remaining, forced_exit_date,
             partial_exits_json, thesis_status, sector, correlation_group, expiry)
            VALUES (?, 0, NULL, ?, ?, ?, ?, ?, ?, ?, '[]', 'active', ?, ?, ?)
            """,
            (
                portfolio_id,
                ticker.upper(),
                instrument_type,
                normalize_capital_tier(capital_tier) or 2,
                entry_date or _today_iso(),
                entry_price or pos.get("avg_cost") or pos.get("mark_price"),
                float(pos["quantity"]),
                forced_exit_date_for_tier(
                    normalize_capital_tier(capital_tier) or 2,
                    _parse_entry(entry_date) or date.today(),
                ),
                sector,
                ticker.upper(),
                pos.get("expiry"),
            ),
        )
        return int(cur.lastrowid)


def _parse_entry(val: Optional[str]) -> Optional[date]:
    if not val:
        return None
    try:
        return date.fromisoformat(str(val)[:10])
    except ValueError:
        return None
