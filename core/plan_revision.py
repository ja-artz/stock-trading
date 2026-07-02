"""Preview and apply structured trading-plan revisions from chat."""

from __future__ import annotations

import copy
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.plan_coherence import apply_plan_item_coherence
from core.plan_sizing import normalize_plan_item_sizing, reconcile_stock_sizing_with_quote
from core.market_quotes import quotes_price_map
from core.portfolio import compute_nav
from core.rules import RuleViolation, validate_trade
from core import store


def _item_to_dict(row: dict) -> dict:
    """Merge DB row + detail_json into trader-agent item shape."""
    detail = row.get("detail") or {}
    if not detail and row.get("detail_json"):
        try:
            detail = json.loads(row["detail_json"])
        except json.JSONDecodeError:
            detail = {}
    item = dict(detail) if isinstance(detail, dict) else {}
    item.update(
        {
            "id": row.get("id"),
            "priority": row.get("priority"),
            "action": row.get("action"),
            "ticker": row.get("ticker"),
            "instrument_type": row.get("instrument_type"),
            "horizon": row.get("horizon"),
            "size_hint": row.get("size_hint"),
            "suggested_notional_usd": row.get("suggested_notional_usd"),
            "suggested_quantity": row.get("suggested_quantity"),
            "quantity_unit": row.get("quantity_unit"),
            "pct_nav": row.get("pct_nav"),
            "pct_cash": row.get("pct_cash"),
            "pct_position": row.get("pct_position"),
            "sizing_summary": row.get("sizing_summary"),
            "rationale": row.get("rationale"),
            "rule_warnings": row.get("rule_warnings"),
            "status": row.get("status"),
            "thesis_type": row.get("thesis_type") or item.get("thesis_type"),
            "persona_consensus": row.get("persona_consensus") or item.get("persona_consensus"),
            "capital_tier": row.get("capital_tier") or item.get("capital_tier"),
            "conviction_grade": row.get("conviction_grade") or item.get("conviction_grade"),
            "sector": row.get("sector") or item.get("sector"),
            "theme_tag": row.get("theme_tag") or item.get("theme_tag"),
            "correlation_group": row.get("correlation_group") or item.get("correlation_group"),
        }
    )
    return normalize_plan_item_sizing(item)


def _attach_rule_warnings(
    item: dict,
    viols: List[RuleViolation],
    warnings: List[str],
) -> None:
    """Trading rules guide plans; chat revisions record violations as warnings only."""
    if not viols:
        return
    existing = list(item.get("rule_warnings") or [])
    for v in viols:
        warnings.append(v.message)
        if v.message not in existing:
            existing.append(v.message)
    item["rule_warnings"] = existing


def _validate_item_proposal(
    item: dict,
    *,
    portfolio_id: int,
    nav_state: dict,
    rules: dict,
    new_pos_week: int,
    quote_bundle: Optional[dict] = None,
) -> List[RuleViolation]:
    violations: List[RuleViolation] = []
    action = (item.get("action") or "").lower()
    if action not in ("buy", "sell", "trim"):
        return violations

    ticker = (item.get("ticker") or "").strip().upper()
    if not ticker:
        violations.append(RuleViolation("missing_ticker", "Trade items require a ticker.", "error"))
        return violations

    instrument = item.get("instrument_type") or "stock"
    qty = item.get("suggested_quantity") or 0
    price = None
    if quote_bundle:
        q = (quote_bundle.get("quotes") or {}).get(ticker) or {}
        price = q.get("price_usd")
    if price is None:
        for p in nav_state.get("positions") or []:
            if (p.get("ticker") or "").upper() == ticker:
                price = p.get("mark_price")
                break
    if price is None or price <= 0:
        if action == "buy" and item.get("suggested_notional_usd"):
            violations.append(
                RuleViolation(
                    "no_price",
                    f"No live quote for {ticker}; sizing cannot be validated.",
                    "warning",
                )
            )
        return violations

    positions = nav_state.get("positions") or []
    is_new = not any((p.get("ticker") or "").upper() == ticker for p in positions)
    side = "buy" if action == "buy" else "sell"
    if action == "trim":
        side = "sell"

    violations.extend(
        validate_trade(
            rules,
            cash_usd=float(nav_state.get("cash_usd") or 0),
            nav_usd=float(nav_state.get("nav_usd") or 0),
            positions=positions,
            side=side,
            ticker=ticker,
            instrument_type=instrument,
            quantity=float(qty or 1),
            price=float(price),
            new_positions_this_week=new_pos_week,
            is_new_position=is_new and action == "buy",
            portfolio_id=portfolio_id,
            plan_item_id=item.get("id"),
        )
    )
    return violations


def _status_change_warning(item: dict, op: str) -> Optional[str]:
    """Advisory note when revising non-pending items via chat (never blocks)."""
    status = (item.get("status") or "pending").lower()
    if op == "remove":
        if status == "pending":
            return None
        if status == "accepted":
            return "Removing an accepted item — consider a trim/sell line instead unless cleaning up."
        if status == "rejected":
            return "Removing a previously rejected item."
        return f"Removing item with status '{status}'."
    if op == "update":
        if status == "rejected":
            return "Updating a previously rejected item (household reconsideration via chat)."
        if status == "accepted":
            return "Updating an accepted item."
        if status == "deferred":
            return "Updating a deferred item."
    return None


def _record_status_change_if_needed(
    plan_item_id: int,
    old_item: dict,
    new_item: dict,
    *,
    summary: Optional[str] = None,
) -> None:
    new_status = (new_item.get("status") or "").lower()
    old_status = (old_item.get("status") or "pending").lower()
    if new_status not in ("accepted", "rejected", "deferred") or new_status == old_status:
        return
    note = f"Chat revision: {summary}" if summary else "Chat revision"
    store.record_decision(plan_item_id, member_id=1, decision=new_status, note=note)


def preview_plan_revision(
    portfolio_id: int,
    weekly_plan_id: int,
    revision: dict,
    *,
    quote_bundle: Optional[dict] = None,
) -> dict[str, Any]:
    plan = store.get_weekly_plan_by_id(weekly_plan_id, portfolio_id)
    if not plan:
        raise ValueError("Trading plan not found")

    session = store.get_active_session()
    rules = store.get_portfolio_rules(portfolio_id, session["rules_json"] if session else "{}")
    nav_state = compute_nav(portfolio_id)
    new_pos_week = store.count_new_positions_this_week(portfolio_id)

    items_by_id = {int(i["id"]): i for i in plan.get("items") or []}
    before: List[dict] = []
    after: List[dict] = []
    errors: List[str] = []
    warnings: List[str] = []
    changes = revision.get("changes") or []

    simulated = {int(k): _item_to_dict(v) for k, v in items_by_id.items()}

    for ch in changes:
        op = (ch.get("op") or "").lower()
        if op == "update":
            pid = int(ch.get("plan_item_id") or 0)
            row = items_by_id.get(pid)
            if not row:
                errors.append(f"Unknown plan_item_id {pid}")
                continue
            base = _item_to_dict(row)
            warn = _status_change_warning(base, "update")
            if warn:
                warnings.append(warn)
            before.append({"op": op, "plan_item_id": pid, "item": copy.deepcopy(base)})
            patched = copy.deepcopy(base)
            patch = ch.get("patch") or {}
            if isinstance(patch.get("sizing"), dict):
                patched.setdefault("sizing", {}).update(patch.pop("sizing"))
            patched.update(patch)
            patched = normalize_plan_item_sizing(patched)
            if quote_bundle:
                sym = (patched.get("ticker") or "").strip().upper()
                live = quotes_price_map(quote_bundle).get(sym)
                if live:
                    patched = reconcile_stock_sizing_with_quote(patched, live, nav_state)
                    patched = normalize_plan_item_sizing(patched)
            plan_date = datetime.now().date()
            patched = apply_plan_item_coherence(patched, plan_date)
            simulated[pid] = patched
            viols = _validate_item_proposal(
                patched,
                portfolio_id=portfolio_id,
                nav_state=nav_state,
                rules=rules,
                new_pos_week=new_pos_week,
                quote_bundle=quote_bundle,
            )
            _attach_rule_warnings(patched, viols, warnings)
            after.append({"op": op, "plan_item_id": pid, "item": patched})

        elif op == "add":
            raw = ch.get("item") or {}
            item = normalize_plan_item_sizing(dict(raw))
            if quote_bundle:
                sym = (item.get("ticker") or "").strip().upper()
                live = quotes_price_map(quote_bundle).get(sym)
                if live:
                    item = reconcile_stock_sizing_with_quote(item, live, nav_state)
                    item = normalize_plan_item_sizing(item)
            item = apply_plan_item_coherence(item, datetime.now().date())
            viols = _validate_item_proposal(
                item,
                portfolio_id=portfolio_id,
                nav_state=nav_state,
                rules=rules,
                new_pos_week=new_pos_week,
                quote_bundle=quote_bundle,
            )
            _attach_rule_warnings(item, viols, warnings)
            after.append({"op": op, "item": item, "temp_key": ch.get("temp_key") or f"new_{len(after)}"})

        elif op == "remove":
            pid = int(ch.get("plan_item_id") or 0)
            row = items_by_id.get(pid)
            if not row:
                errors.append(f"Unknown plan_item_id {pid}")
                continue
            base = _item_to_dict(row)
            warn = _status_change_warning(base, "remove")
            if warn:
                warnings.append(warn)
            before.append({"op": op, "plan_item_id": pid, "item": copy.deepcopy(base)})
            after.append({"op": op, "plan_item_id": pid, "removed": True})
            simulated.pop(pid, None)
        else:
            errors.append(f"Unknown op '{op}'")

    return {
        "weekly_plan_id": weekly_plan_id,
        "summary": revision.get("summary"),
        "before": before,
        "after": after,
        "errors": errors,
        "warnings": warnings,
        "ok": len(errors) == 0,
    }


def apply_plan_revision(
    portfolio_id: int,
    weekly_plan_id: int,
    revision: dict,
    *,
    thread_id: Optional[int] = None,
    quote_bundle: Optional[dict] = None,
) -> dict[str, Any]:
    preview = preview_plan_revision(portfolio_id, weekly_plan_id, revision, quote_bundle=quote_bundle)
    if not preview.get("ok"):
        return {"ok": False, "preview": preview, "errors": preview.get("errors")}

    applied: List[dict] = []
    before_by_id = {
        int(b["plan_item_id"]): b["item"]
        for b in preview.get("before") or []
        if b.get("plan_item_id") is not None
    }
    for entry in preview.get("after") or []:
        op = entry.get("op")
        if op == "update":
            pid = int(entry["plan_item_id"])
            old_item = before_by_id.get(pid) or {}
            store.update_plan_item(pid, portfolio_id, entry["item"])
            _record_status_change_if_needed(
                pid, old_item, entry["item"], summary=revision.get("summary")
            )
            applied.append({"op": "update", "plan_item_id": pid})
        elif op == "add":
            new_id = store.insert_plan_item(weekly_plan_id, portfolio_id, entry["item"])
            applied.append({"op": "add", "plan_item_id": new_id})
        elif op == "remove":
            pid = int(entry["plan_item_id"])
            store.supersede_plan_item(pid, portfolio_id)
            applied.append({"op": "remove", "plan_item_id": pid})

    session = store.get_active_session()
    if session:
        store.append_timeline_event(
            int(session["household_id"]),
            portfolio_id=portfolio_id,
            event_type="plan_chat_revision",
            title=f"Trading plan updated via chat ({len(applied)} change(s))",
            detail={
                "weekly_plan_id": weekly_plan_id,
                "thread_id": thread_id,
                "revision_summary": revision.get("summary"),
                "applied": applied,
            },
        )

    if thread_id:
        store.save_plan_revision_proposal(
            thread_id=thread_id,
            weekly_plan_id=weekly_plan_id,
            portfolio_id=portfolio_id,
            revision=revision,
            preview=preview,
            status="applied",
        )

    return {"ok": True, "preview": preview, "applied": applied}
