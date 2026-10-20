from __future__ import annotations

from datetime import timedelta

import pytest

from order_import import import_orders
from task_manager import reassign_task, update_task_status
from tests.conftest import REFERENCE, order_row, write_csv


def active_task(database, tmp_path):
    row = order_row("ORD-5001", **{"Order Status": "Unconfirmed", "Order Date": (REFERENCE - timedelta(hours=3)).isoformat()})
    file = write_csv(tmp_path / "tasks.csv", [row])
    import_orders(database, file, file.name, "Meera Iyer", REFERENCE)
    return database.list_tasks(False)[0]


def test_reassignment_preserves_deadline_and_status(database, tmp_path):
    task = active_task(database, tmp_path)
    original_deadline, original_status = task["deadline"], task["task_status"]
    reassign_task(database, task["task_id"], "Diya Patel", "Meera Iyer", REFERENCE)
    updated = database.list_tasks(False)[0]
    assert updated["task_id"] == task["task_id"]
    assert updated["assigned_employee"] == "Diya Patel"
    assert updated["deadline"] == original_deadline
    assert updated["task_status"] == original_status


def test_status_transition_and_invalid_assignee(database, tmp_path):
    task = active_task(database, tmp_path)
    update_task_status(database, task["task_id"], "In Progress", "Meera Iyer", clock=REFERENCE)
    assert database.list_tasks(False)[0]["task_status"] == "In Progress"
    with pytest.raises(ValueError, match="active employee"):
        reassign_task(database, task["task_id"], "No Such Employee", "Meera Iyer", REFERENCE)
