"""Unit tests for tier_engine."""

from datetime import date

from core.rules import DEFAULT_RULES
from core.tier_config import resolve_capital_tier_for_plan_item
from core.tier_engine import (
    ProposedEntry,
    build_tier_state,
    evaluate_position_exits,
    pl_pct,
    triage_story_to_tier,
    validate_proposed_entry,
)


def test_tier1_force_exit_at_28_days():
    lot = {
        "id": 1,
        "ticker": "AAPL",
        "capital_tier": 1,
        "entry_date": "2026-01-01",
        "entry_price": 100.0,
        "partial_exits_json": "[]",
        "instrument_type": "stock",
    }
    items = evaluate_position_exits(lot, mark_price=105.0, as_of=date(2026, 1, 29))
    codes = [i.reason_code for i in items]
    assert "tier_1_max_hold_reached" in codes


def test_tier1_profit_25_partial():
    lot = {
        "id": 1,
        "ticker": "AAPL",
        "capital_tier": 1,
        "entry_date": "2026-06-01",
        "entry_price": 100.0,
        "partial_exits_json": "[]",
        "instrument_type": "stock",
    }
    items = evaluate_position_exits(lot, mark_price=126.0, as_of=date(2026, 6, 10))
    assert any(i.reason_code == "tier_1_profit_25" for i in items)


def test_tier1_hard_stop_40():
    lot = {
        "id": 1,
        "ticker": "AAPL",
        "capital_tier": 1,
        "entry_date": "2026-06-01",
        "entry_price": 100.0,
        "partial_exits_json": "[]",
        "instrument_type": "stock",
    }
    items = evaluate_position_exits(lot, mark_price=58.0, as_of=date(2026, 6, 10))
    assert any(i.action == "hard_stop" for i in items)


def test_validate_blocks_tier4_deploy():
    rules = dict(DEFAULT_RULES)
    state = build_tier_state(nav_usd=1000, cash_usd=500, lots=[], rules=rules)
    ok, viols = validate_proposed_entry(
        ProposedEntry(capital_tier=4, ticker="SPY", instrument_type="stock", notional_usd=50),
        state,
        rules,
    )
    assert not ok
    assert any(v["code"] == "tier_4_no_deploy" for v in viols)


def test_triage_passes_on_b_conviction():
    rules = dict(DEFAULT_RULES)
    state = build_tier_state(nav_usd=1000, cash_usd=500, lots=[], rules=rules)
    r = triage_story_to_tier(
        catalyst_weeks=3,
        conviction_grade="B",
        consensus_count=3,
        tier_state=state,
        rules=rules,
    )
    assert r.pass_trade


def test_pl_pct():
    assert abs(pl_pct(100, 125) - 25.0) < 0.01


def test_resolve_capital_tier_from_horizon_when_column_missing():
    assert resolve_capital_tier_for_plan_item({"horizon": "short"}) == 1
    assert resolve_capital_tier_for_plan_item({"capital_tier": 3, "horizon": "short"}) == 3


def test_tier_state_counts_unique_positions_and_prorates_lots():
    rules = dict(DEFAULT_RULES)
    lots = [
        {
            "ticker": "SPY",
            "instrument_type": "stock",
            "capital_tier": 2,
            "market_value": 120.0,
        },
        {
            "ticker": "SPY",
            "instrument_type": "stock",
            "capital_tier": 2,
            "market_value": 115.0,
        },
        {
            "ticker": "ITB",
            "instrument_type": "stock",
            "capital_tier": 2,
            "market_value": 190.0,
        },
    ]
    state = build_tier_state(nav_usd=1000, cash_usd=200, lots=lots, rules=rules)
    bucket = state.buckets[2]
    assert bucket.position_count == 2
    assert abs(bucket.deployed_usd - 425.0) < 0.01
