from __future__ import annotations

import pandas as pd

from order_import import import_orders
from tests.conftest import REFERENCE, order_row, write_csv


def test_valid_csv_import_and_repeat_is_idempotent(database, tmp_path):
    file = write_csv(tmp_path / "orders.csv", [order_row("ORD-3001")])
    first = import_orders(database, file, file.name, "Meera Iyer", REFERENCE)
    second = import_orders(database, file, file.name, "Meera Iyer", REFERENCE)
    assert first["summary"]["inserted_orders"] == 1
    assert second["summary"]["unchanged_orders"] == 1
    assert len(database.list_orders()) == 1


def test_valid_excel_import(database, tmp_path):
    file = tmp_path / "orders.xlsx"
    pd.DataFrame([order_row("ORD-3002")]).to_excel(file, index=False)
    result = import_orders(database, file, file.name, "Meera Iyer", REFERENCE)
    assert result["summary"]["inserted_orders"] == 1


def test_conflicting_existing_identity_is_rejected(database, tmp_path):
    first = write_csv(tmp_path / "one.csv", [order_row("ORD-3003")])
    conflicting = write_csv(tmp_path / "two.csv", [order_row("ORD-3003", **{"Customer Name": "Wrong Customer"})])
    import_orders(database, first, first.name, "Meera Iyer", REFERENCE)
    result = import_orders(database, conflicting, conflicting.name, "Meera Iyer", REFERENCE)
    assert result["summary"]["conflicting_rows"] == 1
    assert database.get_order("ORD-3003")["customer_name"] == "Test Customer"


def test_legitimate_status_update_preserves_order_identity(database, tmp_path):
    first = write_csv(tmp_path / "one.csv", [order_row("ORD-3004")])
    updated = write_csv(tmp_path / "two.csv", [order_row("ORD-3004", **{"Order Status": "Dispatched", "Dispatch Date": "2026-01-19", "Expected Delivery Date": "2026-01-25"})])
    import_orders(database, first, first.name, "Meera Iyer", REFERENCE)
    result = import_orders(database, updated, updated.name, "Meera Iyer", REFERENCE)
    assert result["summary"]["updated_orders"] == 1
    assert database.get_order("ORD-3004")["order_status"] == "Dispatched"
