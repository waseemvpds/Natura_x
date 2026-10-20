"""Small task-management facade used by the UI and tests."""
from __future__ import annotations

from datetime import datetime

from database import Database


def reassign_task(database: Database, task_id: str, employee: str, user: str, clock: datetime | None = None) -> None:
    database.update_task(task_id, assigned_employee=employee, user=user, clock=clock)


def update_task_status(database: Database, task_id: str, status: str, user: str, resolution_notes: str = "", clock: datetime | None = None) -> None:
    database.update_task(task_id, task_status=status, resolution_notes=resolution_notes, user=user, clock=clock)


def update_task_details(database: Database, task_id: str, deadline: str | None, priority: str | None, user: str, clock: datetime | None = None) -> None:
    database.update_task(task_id, deadline=deadline, priority=priority, user=user, clock=clock)
