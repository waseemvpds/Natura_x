from __future__ import annotations

from datetime import timedelta

from order_import import import_orders
from task_manager import reassign_task, update_task_status
from tests.conftest import REFERENCE, order_row, write_csv


def test_task_and_configuration_audits_are_persisted(database, tmp_path):
    row = order_row("ORD-7001", **{"Order Status": "Unconfirmed", "Order Date": (REFERENCE - timedelta(hours=3)).isoformat()})
    file = write_csv(tmp_path / "audit.csv", [row])
    import_orders(database, file, file.name, "Meera Iyer", REFERENCE)
    task = database.list_tasks(False)[0]
    reassign_task(database, task["task_id"], "Diya Patel", "Meera Iyer", REFERENCE)
    update_task_status(database, task["task_id"], "Resolved", "Meera Iyer", "Called customer", REFERENCE)
    database.update_config({"dispatch_hours": 12}, "Meera Iyer", REFERENCE)
    actions = [item["action_performed"] for item in database.audit_logs()]
    assert "Task created and assigned" in actions
    assert "Task reassigned" in actions
    assert "Task status changed" in actions
    assert "Rule configuration changed" in actions


def test_combined_task_update_writes_each_relevant_audit_action(database, tmp_path):
    row = order_row("ORD-7002", **{"Order Status": "Unconfirmed", "Order Date": (REFERENCE - timedelta(hours=3)).isoformat()})
    file = write_csv(tmp_path / "combined_audit.csv", [row])
    import_orders(database, file, file.name, "Meera Iyer", REFERENCE)
    task = database.list_tasks(False)[0]
    database.update_task(
        task["task_id"],
        assigned_employee="Diya Patel",
        task_status="In Progress",
        priority="High",
        deadline="2026-01-20T16:00:00+05:30",
        user="Meera Iyer",
        clock=REFERENCE,
    )
    actions = [item["action_performed"] for item in database.audit_logs()]
    assert {"Task reassigned", "Task status changed", "Task priority changed", "Task deadline changed"} <= set(actions)
