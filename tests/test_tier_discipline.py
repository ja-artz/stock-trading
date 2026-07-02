"""Tests for discipline action-item updates."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.tier_discipline import update_action_item_status


def test_executed_status_reuses_db_connection_for_partial_exit():
    row = {
        "id": 1,
        "portfolio_id": 1,
        "position_lot_id": 42,
        "reason_code": "tier_1_profit_25",
        "detail_json": "{}",
        "status": "open",
    }
    updated_row = {**row, "status": "executed"}

    mock_conn = MagicMock()
    mock_conn.execute.side_effect = [
        MagicMock(fetchone=MagicMock(return_value=row)),
        MagicMock(),
        MagicMock(fetchone=MagicMock(return_value=updated_row)),
    ]

    with patch("core.tier_discipline.db_session") as mock_db_session:
        mock_db_session.return_value.__enter__.return_value = mock_conn
        with patch("core.position_lots.record_partial_exit") as mock_record:
            result = update_action_item_status(1, 1, "executed")

    mock_record.assert_called_once_with(42, "tier_1_profit_25", conn=mock_conn)
    assert result["status"] == "executed"
