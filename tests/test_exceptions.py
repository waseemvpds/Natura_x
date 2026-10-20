from __future__ import annotations

from datetime import timedelta

from order_import import import_orders
from rule_engine import RuleEngine
from task_manager import update_task_status
from tests.conftest import REFERENCE, order_row, write_csv


def test_multiple_exceptions_have_individual_tasks(database, tmp_path):
    row = order_row("ORD-6001", **{"Order Date": "2026-01-10", "Order Status": "Delivery Failed", "Order Value": "7500", "Dispatch Date": "2026-01-15", "Expected Delivery Date": "2026-01-18"})
    file = write_csv(tmp_path / "multiple.csv", [row])
    import_orders(database, file, file.name, "Meera Iyer", REFERENCE)
    assert {item["rule_code"] for item in database.list_exceptions(False)} == {"SHIPMENT_DELAY", "FAILED_DELIVERY", "HIGH_VALUE_OVERDUE"}
    assert len(database.list_tasks(False)) == 3


def test_condition_clearing_resolves_open_exception(database, tmp_path):
    row = order_row("ORD-6002", **{"Order Status": "Unconfirmed", "Order Date": (REFERENCE - timedelta(hours=3)).isoformat()})
    first = write_csv(tmp_path / "one.csv", [row])
    second = write_csv(tmp_path / "two.csv", [order_row("ORD-6002", **{"Order Status": "Confirmed", "Order Date": (REFERENCE - timedelta(minutes=30)).isoformat()})])
    import_orders(database, first, first.name, "Meera Iyer", REFERENCE)
    import_orders(database, second, second.name, "Meera Iyer", REFERENCE)
    assert not database.list_exceptions(False)
    assert database.list_exceptions(True)[0]["exception_status"] == "Resolved"


def test_manual_resolution_is_not_reopened_by_unchanged_upload_but_can_recur(database, tmp_path):
    active = order_row("ORD-6003", **{"Order Status": "Unconfirmed", "Order Date": (REFERENCE - timedelta(hours=3)).isoformat()})
    same = write_csv(tmp_path / "same.csv", [active])
    import_orders(database, same, same.name, "Meera Iyer", REFERENCE)
    task = database.list_tasks(False)[0]
    update_task_status(database, task["task_id"], "Resolved", "Meera Iyer", "Customer confirmed by phone", REFERENCE)
    import_orders(database, same, same.name, "Meera Iyer", REFERENCE)
    assert not database.list_tasks(False)
    cleared = write_csv(tmp_path / "cleared.csv", [order_row("ORD-6003", **{"Order Status": "Confirmed", "Order Date": (REFERENCE - timedelta(minutes=30)).isoformat()})])
    import_orders(database, cleared, cleared.name, "Meera Iyer", REFERENCE)
    import_orders(database, same, same.name, "Meera Iyer", REFERENCE)
    assert len(database.list_tasks(False)) == 1
    assert database.list_exceptions(False)[0]["occurrence_number"] == 2
