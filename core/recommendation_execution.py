"""Infer whether an accepted recommendation is reflected in the paper portfolio."""

from __future__ import annotations

from typing import Any, List, Optional

from core.db import db_session
from core.instruments import find_open_position
from core.portfolio import compute_nav


def _norm_inst(inst: Optional[str]) -> str:
    raw = (inst or "stock").lower()
    if raw in ("call", "put"):
        return f"{raw}_option"
    return raw


def _find_position(
    positions: List[dict],
    ticker: str,
    instrument_type: str,
    *,
    strike: Optional[float] = None,
    expiry: Optional[str] = None,
) -> Optional[dict]:
    return find_open_position(positions, ticker, instrument_type, strike=strike, expiry=expiry)


def _action_side(action: str) -> Optional[str]:
    a = (action or "").lower()
    if a in ("buy", "hedge"):
        return "buy"
    if a in ("sell", "trim"):
        return "sell"
    return None


def _ledger_linked(plan_item_id: int) -> bool:
    with db_session() as conn:
        row = conn.execute(
            "SELECT 1 FROM ledger_events WHERE plan_item_id = ? LIMIT 1",
            (plan_item_id,),
        ).fetchone()
        return row is not None


def _ledger_matches_since(
    portfolio_id: int,
    *,
    ticker: str,
    instrument_type: str,
    side: str,
    decided_at: str,
) -> bool:
    inst = _norm_inst(instrument_type)
    want_side = side.lower()
    with db_session() as conn:
        rows = conn.execute(
            """
            SELECT instrument_type, side FROM ledger_events
            WHERE portfolio_id = ?
              AND UPPER(ticker) = ?
              AND logged_at >= ?
            """,
            (portfolio_id, ticker.upper(), decided_at),
        ).fetchall()
    for row in rows:
        if _norm_inst(row["instrument_type"]) == inst and (row["side"] or "").lower() == want_side:
            return True
    return False


def infer_execution_status(item: dict[str, Any], portfolio_id: int) -> Optional[str]:
    """
    For accepted recommendations: 'executed' if portfolio/ledger reflects the trade, else 'pending'.
    Returns None when not applicable (not accepted, or watch/hold).
    """
    if (item.get("status") or "").lower() != "accepted":
        return None

    action = (item.get("action") or "").lower()
    if action in ("watch", "hold"):
        return None

    plan_item_id = int(item["id"])
    if _ledger_linked(plan_item_id):
        return "executed"

    decided_at = (item.get("latest_decision") or {}).get("decided_at")
    side = _action_side(action)
    ticker = (item.get("ticker") or "").strip().upper()
    if not ticker or not side:
        return "pending"

    inst = item.get("instrument_type") or "stock"
    if decided_at and _ledger_matches_since(
        portfolio_id,
        ticker=ticker,
        instrument_type=inst,
        side=side,
        decided_at=decided_at,
    ):
        return "executed"

    nav = compute_nav(portfolio_id)
    positions = nav.get("positions") or []
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    strike = item.get("option_strike") or detail.get("option_strike")
    expiry = item.get("option_expiry") or detail.get("option_expiry")
    oc = item.get("option_contract") if isinstance(item.get("option_contract"), dict) else {}
    if not oc and isinstance(detail.get("option_contract"), dict):
        oc = detail["option_contract"]
    if oc:
        strike = strike or oc.get("strike")
        expiry = expiry or oc.get("expiry")
    pos = _find_position(positions, ticker, inst, strike=strike, expiry=expiry)

    if side == "buy":
        if pos and float(pos.get("quantity") or 0) > 1e-9:
            return "executed"
        return "pending"

    if side == "sell":
        if not pos or float(pos.get("quantity") or 0) <= 1e-9:
            return "executed"
        return "pending"

    return "pending"


def attach_execution_status(items: List[dict], portfolio_id: int) -> None:
    for item in items:
        item["execution_status"] = infer_execution_status(item, portfolio_id)
