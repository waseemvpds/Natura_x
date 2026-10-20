from __future__ import annotations

from datetime import timedelta

from database import Database
from order_import import import_orders
from task_manager import reassign_task
from tests.conftest import REFERENCE, order_row, write_csv


def test_records_survive_new_database_instance(tmp_path):
    path = tmp_path / "persistent.db"
    first = Database(path)
    first.initialize()
    file = write_csv(tmp_path / "persist.csv", [order_row("ORD-8001", **{"Order Status": "Unconfirmed", "Order Date": (REFERENCE - timedelta(hours=3)).isoformat()})])
    import_orders(first, file, file.name, "Meera Iyer", REFERENCE)
    task = first.list_tasks(False)[0]
    reassign_task(first, task["task_id"], "Diya Patel", "Meera Iyer", REFERENCE)
    first.update_config({"dispatch_hours": 12}, "Meera Iyer", REFERENCE)
    second = Database(path)
    assert second.get_order("ORD-8001") is not None
    assert second.list_tasks(False)[0]["assigned_employee"] == "Diya Patel"
    assert second.get_config()["dispatch_hours"] == "12"
    assert second.audit_logs()
    assert second.import_histories()
