from __future__ import annotations

import pandas as pd

from data_validation import validate_frame
from tests.conftest import order_row


def test_normalizes_common_headers_and_values():
    row = order_row("ORD-2001", **{"Payment Type": " prepaid ", "Order Status": " confirmed "})
    row = {key.replace(" ", "_").lower(): value for key, value in row.items()}
    result = validate_frame(pd.DataFrame([row]))
    assert result.rows[0].outcome == "Valid"
    assert result.rows[0].order["payment_type"] == "Prepaid"
    assert result.rows[0].order["order_status"] == "Confirmed"


def test_missing_column_is_a_structural_error():
    row = order_row()
    del row["Order Value"]
    result = validate_frame(pd.DataFrame([row]))
    assert result.structural_issues
    assert result.structural_issues[0]["category"] == "Missing column"


def test_invalid_core_values_are_not_processable():
    row = order_row("ORD-2002", **{"Order Value": "NaN", "Order Date": "not a date", "Payment Type": "Credit"})
    result = validate_frame(pd.DataFrame([row]))
    assert result.rows[0].outcome == "Invalid"
    assert result.rows[0].order is None
    assert {item["column_name"] for item in result.issues} >= {"order_value", "order_date", "payment_type"}


def test_missing_expected_date_is_needs_correction_not_false_overdue():
    row = order_row("ORD-2003", **{"Order Status": "Dispatched", "Dispatch Date": "2026-01-19", "Expected Delivery Date": ""})
    result = validate_frame(pd.DataFrame([row]))
    assert result.rows[0].outcome == "Needs Correction"
    assert result.rows[0].order["expected_delivery_date"] is None


def test_duplicate_and_conflicting_ids_are_quarantined():
    exact = order_row("ORD-DUP")
    conflict = order_row("ORD-CONFLICT")
    different = order_row("ORD-CONFLICT", **{"Customer Name": "Someone Else"})
    result = validate_frame(pd.DataFrame([exact, exact.copy(), conflict, different]))
    assert [row.outcome for row in result.rows] == ["Valid", "Duplicate", "Conflict", "Conflict"]
