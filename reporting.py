"""Consistent dashboard/report data projections from the persistent database."""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from config import TIMEZONE
from database import Database


def task_is_overdue(task: dict[str, Any], now: datetime | None = None) -> bool:
    if task["task_status"] == "Resolved":
        return False
    reference = now or datetime.now(TIMEZONE)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=TIMEZONE)
    return datetime.fromisoformat(task["deadline"]).astimezone(TIMEZONE) < reference


def task_is_approaching(task: dict[str, Any], warning_hours: float, now: datetime | None = None) -> bool:
    if task["task_status"] == "Resolved":
        return False
    reference = now or datetime.now(TIMEZONE)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=TIMEZONE)
    due = datetime.fromisoformat(task["deadline"]).astimezone(TIMEZONE)
    seconds = (due - reference).total_seconds()
    return 0 <= seconds <= warning_hours * 3600


def daily_report(database: Database, now: datetime | None = None) -> dict[str, pd.DataFrame]:
    exceptions = pd.DataFrame(database.list_exceptions(include_resolved=True))
    tasks = pd.DataFrame(database.list_tasks(include_resolved=True))
    if exceptions.empty:
        return {name: pd.DataFrame() for name in ("New exceptions", "Unresolved exceptions", "Overdue tasks", "High-priority cases", "Employee pending actions")}
    today = (now or datetime.now(TIMEZONE)).date().isoformat()
    tasks["is_overdue"] = tasks.apply(lambda row: task_is_overdue(row.to_dict(), now), axis=1) if not tasks.empty else []
    reports = {
        "New exceptions": exceptions[exceptions["first_detected_at"].str.startswith(today)].copy(),
        "Unresolved exceptions": exceptions[exceptions["exception_status"] == "Open"].copy(),
        "Overdue tasks": tasks[tasks["is_overdue"]].copy() if not tasks.empty else pd.DataFrame(),
        "High-priority cases": exceptions[(exceptions["priority"] == "High") & (exceptions["exception_status"] == "Open")].copy(),
    }
    pending = tasks[tasks["task_status"].isin(["Open", "In Progress"])].copy() if not tasks.empty else pd.DataFrame()
    reports["Employee pending actions"] = (pending.groupby("assigned_employee", as_index=False)
                                            .agg(pending_tasks=("task_id", "count"), high_priority_tasks=("priority", lambda values: (values == "High").sum()),
                                                 overdue_tasks=("is_overdue", "sum")) if not pending.empty else pd.DataFrame(columns=["assigned_employee", "pending_tasks", "high_priority_tasks", "overdue_tasks"]))
    return reports


def combined_report_csv(reports: dict[str, pd.DataFrame]) -> bytes:
    frames = []
    for report_name, frame in reports.items():
        if not frame.empty:
            item = frame.copy()
            item.insert(0, "report_category", report_name)
            frames.append(item)
    return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame({"report_category": []})).to_csv(index=False).encode("utf-8")
