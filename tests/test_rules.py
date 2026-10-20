from __future__ import annotations

from datetime import timedelta

from rule_engine import RuleEngine
from tests.conftest import REFERENCE, order_row, write_csv
from order_import import import_orders


def load(database, tmp_path, row):
    file = write_csv(tmp_path / f"{row['Order ID']}.csv", [row])
    import_orders(database, file, file.name, "Meera Iyer", REFERENCE)
    return RuleEngine(database).explain_order(row["Order ID"], REFERENCE)


def state(items, code):
    return next(item["state"] for item in items if item["rule_code"] == code)


def test_exact_unconfirmed_and_dispatch_boundaries(database, tmp_path):
    unconfirmed = order_row("ORD-4001", **{"Order Status": "Unconfirmed", "Order Date": (REFERENCE - timedelta(hours=2)).isoformat()})
    confirmed = order_row("ORD-4002", **{"Order Status": "Confirmed", "Order Date": (REFERENCE - timedelta(hours=24)).isoformat()})
    assert state(load(database, tmp_path, unconfirmed), "UNCONFIRMED") == "No match"
    assert state(load(database, tmp_path, confirmed), "DISPATCH_DELAY") == "No match"


def test_all_overdue_rules_and_strict_value_boundary(database, tmp_path):
    row = order_row("ORD-4003", **{"Order Date": "2026-01-10", "Order Status": "Delivery Failed", "Order Value": "5000.01", "Dispatch Date": "2026-01-15", "Expected Delivery Date": "2026-01-18"})
    matches = {item["rule_code"] for item in load(database, tmp_path, row) if item["state"] == "Match"}
    assert matches == {"SHIPMENT_DELAY", "FAILED_DELIVERY", "HIGH_VALUE_OVERDUE"}
    exact = order_row("ORD-4004", **{"Order Date": "2026-01-10", "Order Status": "Dispatched", "Order Value": "5000", "Dispatch Date": "2026-01-15", "Expected Delivery Date": "2026-01-18"})
    assert state(load(database, tmp_path, exact), "HIGH_VALUE_OVERDUE") == "No match"


def test_missing_expected_date_cannot_evaluate_overdue(database, tmp_path):
    row = order_row("ORD-4005", **{"Order Status": "Dispatched", "Dispatch Date": "2026-01-15", "Expected Delivery Date": ""})
    items = load(database, tmp_path, row)
    assert state(items, "SHIPMENT_DELAY") == "Cannot evaluate"
    assert state(items, "HIGH_VALUE_OVERDUE") == "Cannot evaluate"


def test_repeated_rule_runs_do_not_duplicate_active_tasks(database, tmp_path):
    row = order_row("ORD-4006", **{"Order Status": "Unconfirmed", "Order Date": (REFERENCE - timedelta(hours=3)).isoformat()})
    load(database, tmp_path, row)
    engine = RuleEngine(database)
    engine.reevaluate_all(clock=REFERENCE)
    engine.reevaluate_all(clock=REFERENCE)
    assert len(database.list_exceptions(False)) == 1
    assert len(database.list_tasks(False)) == 1
