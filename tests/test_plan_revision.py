"""Tests for chat-driven trading plan revisions."""

from __future__ import annotations

from unittest.mock import patch

from core.plan_revision import preview_plan_revision
from core.rules import RuleViolation


def test_rule_violations_are_warnings_not_blocks():
    plan = {
        "id": 1,
        "items": [
            {
                "id": 10,
                "status": "pending",
                "action": "buy",
                "ticker": "AAPL",
                "instrument_type": "stock",
                "suggested_quantity": 10,
                "detail_json": "{}",
            }
        ],
    }
    revision = {
        "summary": "Increase size",
        "changes": [
            {
                "op": "update",
                "plan_item_id": 10,
                "patch": {"suggested_notional_usd": 50000},
            }
        ],
    }
    nav_state = {
        "nav_usd": 10000,
        "cash_usd": 8000,
        "positions": [],
    }

    with patch("core.plan_revision.store.get_weekly_plan_by_id", return_value=plan):
        with patch("core.plan_revision.store.get_active_session", return_value={"rules_json": "{}"}):
            with patch("core.plan_revision.store.get_portfolio_rules", return_value={}):
                with patch("core.plan_revision.store.count_new_positions_this_week", return_value=0):
                    with patch("core.plan_revision.compute_nav", return_value=nav_state):
                        with patch(
                            "core.plan_revision._validate_item_proposal",
                            return_value=[
                                RuleViolation(
                                    "max_position_pct",
                                    "Position would exceed 33% of NAV (~$3300.00).",
                                    "error",
                                )
                            ],
                        ):
                            preview = preview_plan_revision(1, 1, revision)

    assert preview["ok"] is True
    assert preview["errors"] == []
    assert len(preview["warnings"]) == 1
    assert "33%" in preview["warnings"][0]
    item = preview["after"][0]["item"]
    assert item["rule_warnings"] == [preview["warnings"][0]]


def test_rejected_item_update_is_allowed_with_warning():
    plan = {
        "id": 1,
        "items": [
            {
                "id": 230,
                "status": "rejected",
                "action": "buy",
                "ticker": "TLT",
                "instrument_type": "stock",
                "suggested_quantity": 1,
                "detail_json": "{}",
            }
        ],
    }
    revision = {
        "summary": "Retroactive attribution for executed TLT call",
        "changes": [
            {
                "op": "update",
                "plan_item_id": 230,
                "patch": {
                    "instrument_type": "call_option",
                    "status": "accepted",
                    "sizing_summary": "1 TLT call executed",
                },
            }
        ],
    }
    nav_state = {"nav_usd": 10000, "cash_usd": 5000, "positions": []}

    with patch("core.plan_revision.store.get_weekly_plan_by_id", return_value=plan):
        with patch("core.plan_revision.store.get_active_session", return_value={"rules_json": "{}"}):
            with patch("core.plan_revision.store.get_portfolio_rules", return_value={}):
                with patch("core.plan_revision.store.count_new_positions_this_week", return_value=0):
                    with patch("core.plan_revision.compute_nav", return_value=nav_state):
                        with patch("core.plan_revision._validate_item_proposal", return_value=[]):
                            preview = preview_plan_revision(1, 1, revision)

    assert preview["ok"] is True
    assert preview["errors"] == []
    assert any("rejected" in w.lower() for w in preview["warnings"])
    item = preview["after"][0]["item"]
    assert item["status"] == "accepted"
    assert item["instrument_type"] == "call_option"


def test_apply_records_status_change():
    plan = {
        "id": 1,
        "items": [
            {
                "id": 230,
                "status": "rejected",
                "action": "buy",
                "ticker": "TLT",
                "instrument_type": "stock",
                "detail_json": "{}",
            }
        ],
    }
    revision = {
        "summary": "Mark accepted after execution",
        "changes": [
            {"op": "update", "plan_item_id": 230, "patch": {"status": "accepted"}},
        ],
    }
    nav_state = {"nav_usd": 10000, "cash_usd": 5000, "positions": []}

    with patch("core.plan_revision.store.get_weekly_plan_by_id", return_value=plan):
        with patch("core.plan_revision.store.get_active_session", return_value={"household_id": 1, "rules_json": "{}"}):
            with patch("core.plan_revision.store.get_portfolio_rules", return_value={}):
                with patch("core.plan_revision.store.count_new_positions_this_week", return_value=0):
                    with patch("core.plan_revision.compute_nav", return_value=nav_state):
                        with patch("core.plan_revision._validate_item_proposal", return_value=[]):
                            with patch("core.plan_revision.store.update_plan_item") as mock_update:
                                with patch("core.plan_revision.store.record_decision") as mock_decision:
                                    with patch("core.plan_revision.store.append_timeline_event"):
                                        from core.plan_revision import apply_plan_revision

                                        result = apply_plan_revision(1, 1, revision)

    assert result["ok"] is True
    mock_update.assert_called_once()
    mock_decision.assert_called_once_with(
        230, member_id=1, decision="accepted", note="Chat revision: Mark accepted after execution"
    )


def test_structural_errors_still_block():
    plan = {"id": 1, "items": []}
    revision = {
        "changes": [{"op": "update", "plan_item_id": 99, "patch": {"ticker": "MSFT"}}],
    }

    with patch("core.plan_revision.store.get_weekly_plan_by_id", return_value=plan):
        with patch("core.plan_revision.store.get_active_session", return_value={"rules_json": "{}"}):
            with patch("core.plan_revision.store.get_portfolio_rules", return_value={}):
                with patch("core.plan_revision.store.count_new_positions_this_week", return_value=0):
                    with patch(
                        "core.plan_revision.compute_nav",
                        return_value={"nav_usd": 10000, "cash_usd": 5000, "positions": []},
                    ):
                        preview = preview_plan_revision(1, 1, revision)

    assert preview["ok"] is False
    assert any("Unknown plan_item_id" in e for e in preview["errors"])
