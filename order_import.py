"""File parsing, import comparison, persistence, and post-import rule evaluation."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from data_validation import CANONICAL_COLUMNS, ValidationResult, _issue, validate_frame
from database import Database
from rule_engine import RuleEngine


def read_order_file(source: str | Path | bytes | BinaryIO, filename: str | None = None) -> pd.DataFrame:
    name = (filename or (str(source) if isinstance(source, (str, Path)) else "upload")).lower()
    if name.endswith(".csv"):
        return pd.read_csv(source)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(source, engine="openpyxl")
    raise ValueError("Unsupported file type. Upload a .csv, .xlsx, or .xls file.")


def _identity_conflict(incoming: dict[str, Any], existing: dict[str, Any]) -> bool:
    """Customer identity is immutable; status/dates/value may be legitimate subsequent updates."""
    return any(incoming[field] != existing[field] for field in ("customer_name", "phone_number", "payment_type"))


def import_orders(database: Database, source: str | Path | bytes | BinaryIO, filename: str, user: str,
                  clock: datetime | None = None) -> dict[str, Any]:
    frame = read_order_file(source, filename)
    result: ValidationResult = validate_frame(frame)
    summary: dict[str, Any] = {
        "filename": filename, "user": user, "total_rows": len(frame), "valid_rows": 0, "needs_correction_rows": 0,
        "invalid_rows": 0, "duplicate_rows": 0, "conflicting_rows": 0, "inserted_orders": 0,
        "updated_orders": 0, "unchanged_orders": 0, "rejected_rows": 0, "notes": "",
    }
    if result.structural_issues:
        summary["invalid_rows"] = len(frame)
        summary["rejected_rows"] = len(frame)
        summary["notes"] = "The file has missing or ambiguous required columns; no rows were imported."
        with database.connection() as conn:
            import_id = database.save_import_history(conn, summary, clock)
            database.save_quality_issues(conn, import_id, result.issues, clock)
        return {"summary": summary, "issues": result.issues, "validation": result, "rule_result": None}
    issues = list(result.issues)
    # Cross-upload identity conflicts are quarantined. A matching identity allows a deterministic update.
    for row in result.processable:
        existing = database.get_order(row.order["order_id"])
        if existing and _identity_conflict(row.order, existing):
            row.outcome, row.order = "Conflict", None
            issue = _issue(row.source_row, existing["order_id"], "order_id", "Conflicting existing ID",
                           "The incoming record has a different customer identity or payment type from the stored order.",
                           "Verify the order ID and customer identity before importing.", "Conflict")
            row.issues.append(issue)
            issues.append(issue)
    with database.connection() as conn:
        for row in result.rows:
            if row.outcome == "Valid" and row.order:
                summary["valid_rows"] += 1
            elif row.outcome == "Needs Correction" and row.order:
                summary["needs_correction_rows"] += 1
            elif row.outcome == "Duplicate":
                summary["duplicate_rows"] += 1
                summary["rejected_rows"] += 1
            elif row.outcome == "Conflict":
                summary["conflicting_rows"] += 1
                summary["rejected_rows"] += 1
            else:
                summary["invalid_rows"] += 1
                summary["rejected_rows"] += 1
            if row.order:
                action = database.upsert_order(conn, row.order, clock)
                summary[f"{action}_orders"] += 1
        import_id = database.save_import_history(conn, summary, clock)
        database.save_quality_issues(conn, import_id, issues, clock)
    engine = RuleEngine(database)
    rule_result = engine.reevaluate_all(user="Rule Engine", clock=clock)
    return {"summary": summary, "issues": issues, "validation": result, "rule_result": rule_result}
