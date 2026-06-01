"""Plan-item trade helpers (legacy auto-execute removed; use Portfolio log + recommendation_execution)."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from core.db import db_session, row_to_dict
from core.ledger import log_trade
from core.plan_coherence import normalize_option_contract
from core.portfolio import compute_nav
from core.pricing import get_last_price
from core.instruments import OPTION_CONTRACT_MULTIPLIER
from core.rules import is_option_instrument


def _merge_item_detail(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    if item.get("persona_consensus") and isinstance(item["persona_consensus"], str):
        item["persona_consensus"] = json.loads(item["persona_consensus"])
    if item.get("rule_warnings") and isinstance(item["rule_warnings"], str):
        item["rule_warnings"] = json.loads(item["rule_warnings"])
    detail = item.get("detail_json")
    if detail:
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                detail = None
        if isinstance(detail, dict):
            for k, v in detail.items():
                if item.get(k) in (None, "", {}):
                    item[k] = v
    return normalize_option_contract(item)


def get_plan_item(plan_item_id: int) -> Optional[dict[str, Any]]:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT pi.*, wp.portfolio_id, wp.id AS weekly_plan_id
            FROM plan_items pi
            JOIN weekly_plans wp ON wp.id = pi.weekly_plan_id
            WHERE pi.id = ?
            """,
            (plan_item_id,),
        ).fetchone()
        if not row:
            return None
        return _merge_item_detail(row_to_dict(row))


def get_auto_trade_for_plan_item(plan_item_id: int) -> Optional[dict[str, Any]]:
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT id, side, ticker, instrument_type, quantity, price, logged_at, note
            FROM ledger_events
            WHERE plan_item_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (plan_item_id,),
        ).fetchone()
        return row_to_dict(row) if row else None


def undo_auto_trade_for_plan_item(plan_item_id: int) -> dict[str, Any]:
    """Remove ledger trade linked to this plan item and reset item to pending."""
    item = get_plan_item(plan_item_id)
    if not item:
        return {"ok": False, "reason": "Plan item not found"}

    trade = get_auto_trade_for_plan_item(plan_item_id)
    if not trade:
        return {"ok": False, "reason": "No auto-logged trade found for this recommendation"}

    with db_session() as conn:
        conn.execute("DELETE FROM ledger_events WHERE id = ?", (trade["id"],))
        conn.execute("DELETE FROM decisions WHERE plan_item_id = ?", (plan_item_id,))
        conn.execute("UPDATE plan_items SET status = 'pending' WHERE id = ?", (plan_item_id,))

    from core.snapshots import save_snapshot

    snap = save_snapshot(int(item["portfolio_id"]))
    return {
        "ok": True,
        "removed_ledger_event_id": trade["id"],
        "plan_item_id": plan_item_id,
        "status": "pending",
        "snapshot": snap,
    }


def _ledger_exists_for_plan_item(plan_item_id: int) -> bool:
    with db_session() as conn:
        row = conn.execute(
            "SELECT id FROM ledger_events WHERE plan_item_id = ? LIMIT 1",
            (plan_item_id,),
        ).fetchone()
        return row is not None


def _infer_premium_usd(item: dict[str, Any]) -> Optional[float]:
    notional = item.get("suggested_notional_usd")
    if notional is not None and float(notional) > 0:
        return float(notional)
    text = f"{item.get('sizing_summary') or ''} {item.get('rationale') or ''}"
    m = re.search(r"~\s*\$?\s*([\d,]+(?:\.\d+)?)\s*premium", text, re.I)
    if m:
        return float(m.group(1).replace(",", ""))
    m = re.search(r"~\s*\$?\s*([\d,]+(?:\.\d+)?)\s*(?:in|for)\s", text, re.I)
    if m and (item.get("action") or "").lower() == "buy":
        return float(m.group(1).replace(",", ""))
    return None


def _action_to_side(action: str) -> Optional[str]:
    a = (action or "").lower()
    if a in ("buy", "hedge"):
        return "buy"
    if a in ("sell", "trim"):
        return "sell"
    return None


def _resolve_quantity(item: dict[str, Any], side: str, nav_state: dict[str, Any]) -> Optional[float]:
    qty = item.get("suggested_quantity")
    if qty is not None and float(qty) > 0:
        return float(qty)

    ticker = (item.get("ticker") or "").upper()
    inst = item.get("instrument_type") or "stock"
    positions = nav_state.get("positions") or []

    if side == "sell":
        pct = item.get("pct_position")
        if pct is not None:
            pos = next(
                (
                    p
                    for p in positions
                    if p.get("ticker", "").upper() == ticker
                    and (p.get("instrument_type") or "stock") == inst
                ),
                None,
            )
            if not pos:
                pos = next((p for p in positions if p.get("ticker", "").upper() == ticker), None)
            if pos and float(pos.get("quantity", 0)) > 0:
                return max(0.0, float(pos["quantity"]) * float(pct) / 100.0)

    premium = _infer_premium_usd(item) if is_option_instrument(inst) else None
    notional = premium if premium is not None else item.get("suggested_notional_usd")
    if notional is not None and float(notional) > 0:
        if is_option_instrument(inst):
            item.setdefault("suggested_notional_usd", float(notional))
            return max(1.0, float(item.get("suggested_quantity") or 1))
        mark = get_last_price(ticker)
        if mark and mark > 0:
            return max(0.0, float(notional) / mark)

    if side == "buy":
        pct_cash = item.get("pct_cash")
        if pct_cash is not None and nav_state.get("cash_usd"):
            cash_slice = float(nav_state["cash_usd"]) * float(pct_cash) / 100.0
            mark = get_last_price(ticker)
            if mark and mark > 0:
                if is_option_instrument(inst):
                    return max(1.0, math.floor(cash_slice / (mark * 100)))
                return max(0.0, round(cash_slice / mark, 6))

    return None


def _resolve_price(item: dict[str, Any], quantity: float) -> Optional[float]:
    ticker = (item.get("ticker") or "").upper()
    inst = item.get("instrument_type") or "stock"
    notional = _infer_premium_usd(item) if is_option_instrument(inst) else item.get("suggested_notional_usd")

    if notional and quantity > 0:
        if is_option_instrument(inst):
            return float(notional) / (quantity * OPTION_CONTRACT_MULTIPLIER)
        return float(notional) / quantity

    mark = get_last_price(ticker)
    if mark and mark > 0 and not is_option_instrument(inst):
        return float(mark)
    return None


def build_trade_from_plan_item(item: dict[str, Any]) -> dict[str, Any]:
    """Build log_trade kwargs or return {ok: False, reason}."""
    action = (item.get("action") or "").lower()
    if action in ("watch", "hold"):
        return {"ok": False, "skipped": True, "reason": f"Action '{action}' does not create a trade"}

    side = _action_to_side(action)
    if not side:
        return {"ok": False, "reason": f"Unsupported action '{action}' for auto-execution"}

    ticker = (item.get("ticker") or "").strip().upper()
    if not ticker:
        return {"ok": False, "reason": "Missing ticker on plan item"}

    inst = (item.get("instrument_type") or "stock").lower()
    if inst in ("call", "put"):
        inst = f"{inst}_option"
    portfolio_id = int(item["portfolio_id"])

    nav_state = compute_nav(portfolio_id)
    quantity = _resolve_quantity(item, side, nav_state)
    if not quantity or quantity <= 0:
        return {
            "ok": False,
            "reason": "Could not derive quantity — log this trade manually in Portfolio",
        }

    price = _resolve_price(item, quantity)
    if not price or price <= 0:
        return {
            "ok": False,
            "reason": f"Could not price {ticker} — log this trade manually in Portfolio",
        }

    strike = item.get("option_strike")
    expiry = item.get("option_expiry")
    oc = item.get("option_contract")
    if isinstance(oc, dict):
        strike = strike or oc.get("strike")
        expiry = expiry or oc.get("expiry")

    return {
        "ok": True,
        "portfolio_id": portfolio_id,
        "side": side,
        "ticker": ticker,
        "instrument_type": inst,
        "quantity": round(quantity, 6),
        "price": round(price, 4),
        "strike": float(strike) if strike is not None and str(strike).strip() else None,
        "expiry": str(expiry) if expiry else None,
        "plan_item_id": int(item["id"]),
        "weekly_plan_id": int(item["weekly_plan_id"]),
    }


def execute_accepted_plan_item(
    plan_item_id: int,
    member_id: int,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Log a paper trade for an accepted recommendation (idempotent per plan_item_id)."""
    if _ledger_exists_for_plan_item(plan_item_id):
        return {
            "ok": True,
            "already_executed": True,
            "message": "Trade already logged for this recommendation",
        }

    item = get_plan_item(plan_item_id)
    if not item:
        return {"ok": False, "reason": "Plan item not found"}

    trade_spec = build_trade_from_plan_item(item)
    if not trade_spec.get("ok"):
        if trade_spec.get("skipped"):
            return trade_spec
        return trade_spec

    exec_note = note or ""
    if exec_note:
        exec_note = f"{exec_note} | "
    exec_note += "Auto-logged from accepted weekly plan item"

    result = log_trade(
        trade_spec["portfolio_id"],
        side=trade_spec["side"],
        ticker=trade_spec["ticker"],
        instrument_type=trade_spec["instrument_type"],
        quantity=trade_spec["quantity"],
        price=trade_spec["price"],
        strike=trade_spec.get("strike"),
        expiry=trade_spec.get("expiry"),
        plan_item_id=plan_item_id,
        member_id=member_id,
        note=exec_note,
        weekly_plan_id=trade_spec["weekly_plan_id"],
        block_on_violations=True,
    )

    if not result.get("ok"):
        return {
            "ok": False,
            "reason": "Trade blocked by rules",
            "violations": result.get("violations"),
        }

    return {
        "ok": True,
        "ledger_event_id": result.get("ledger_event_id"),
        "trade": {
            "side": trade_spec["side"],
            "ticker": trade_spec["ticker"],
            "quantity": trade_spec["quantity"],
            "price": trade_spec["price"],
            "instrument_type": trade_spec["instrument_type"],
        },
        "snapshot": result.get("snapshot"),
    }
