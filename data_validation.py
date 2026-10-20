"""Input normalization and transparent row-level validation."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd

from config import PAYMENT_TYPES, SUPPORTED_STATUSES, TERMINAL_STATUSES, TIMEZONE

CANONICAL_COLUMNS = [
    "order_id", "order_date", "customer_name", "phone_number", "order_value",
    "payment_type", "order_status", "dispatch_date", "expected_delivery_date", "assigned_employee",
]

ALIASES = {
    "order_id": {"orderid", "order_id", "order id", "id"},
    "order_date": {"orderdate", "order_date", "order date", "createdat", "createddate"},
    "customer_name": {"customername", "customer_name", "customer name", "name"},
    "phone_number": {"phonenumber", "phone_number", "phone number", "phone", "mobile", "mobilenumber"},
    "order_value": {"ordervalue", "order_value", "order value", "amount", "value"},
    "payment_type": {"paymenttype", "payment_type", "payment type", "payment"},
    "order_status": {"orderstatus", "order_status", "order status", "status"},
    "dispatch_date": {"dispatchdate", "dispatch_date", "dispatch date", "shippeddate"},
    "expected_delivery_date": {"expecteddeliverydate", "expected_delivery_date", "expected delivery date", "deliverydate", "eta"},
    "assigned_employee": {"assignedemployee", "assigned_employee", "assigned employee", "assignee", "employee"},
}

STATUS_MAP = {
    "unconfirmed": "Unconfirmed", "confirmed": "Confirmed", "dispatched": "Dispatched",
    "outfordelivery": "Out for Delivery", "out for delivery": "Out for Delivery",
    "delivered": "Delivered", "deliveryfailed": "Delivery Failed", "delivery failed": "Delivery Failed",
    "cancelled": "Cancelled", "canceled": "Cancelled", "returned": "Returned",
}
PAYMENT_MAP = {"prepaid": "Prepaid", "cod": "COD"}


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).strip().lower())


def _clean(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)) or pd.isna(value):
        return None
    try:
        if isinstance(value, pd.Timestamp):
            parsed = value.to_pydatetime()
        elif isinstance(value, (datetime, date)):
            parsed = datetime.combine(value, datetime.min.time()) if isinstance(value, date) and not isinstance(value, datetime) else value
        else:
            parsed = pd.to_datetime(str(value), errors="raise").to_pydatetime()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TIMEZONE)
        return parsed.astimezone(TIMEZONE).isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError):
        return None


def _issue(source_row: int, order_id: str | None, column: str, category: str, explanation: str,
           recommendation: str, outcome: str) -> dict[str, Any]:
    return {
        "source_row": source_row, "order_id": order_id, "column_name": column,
        "category": category, "explanation": explanation, "recommendation": recommendation,
        "processing_outcome": outcome,
    }


@dataclass
class ValidatedRow:
    source_row: int
    order: dict[str, Any] | None
    issues: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = "Valid"  # Valid, Needs Correction, Invalid, Duplicate, Conflict


@dataclass
class ValidationResult:
    rows: list[ValidatedRow]
    issues: list[dict[str, Any]]
    normalized_columns: dict[str, str]
    structural_issues: list[dict[str, Any]]

    @property
    def processable(self) -> list[ValidatedRow]:
        return [row for row in self.rows if row.outcome in {"Valid", "Needs Correction"} and row.order]


def normalize_columns(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str], list[dict[str, Any]]]:
    candidates: dict[str, list[str]] = {column: [] for column in CANONICAL_COLUMNS}
    for original in frame.columns:
        normalized = _key(original)
        for canonical, aliases in ALIASES.items():
            if normalized in {_key(alias) for alias in aliases}:
                candidates[canonical].append(str(original))
    issues: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}
    for canonical, matches in candidates.items():
        if not matches:
            issues.append(_issue(0, None, canonical, "Missing column", f"The required column '{canonical}' is absent.", "Add the column with a clear header.", "Invalid"))
        elif len(matches) > 1:
            issues.append(_issue(0, None, canonical, "Ambiguous column", f"Columns {', '.join(matches)} all map to '{canonical}'.", "Keep only one equivalent column.", "Invalid"))
        else:
            mapping[canonical] = matches[0]
    if issues:
        return frame, mapping, issues
    normalized = frame.rename(columns={source: target for target, source in mapping.items()})
    return normalized[CANONICAL_COLUMNS].copy(), mapping, issues


def validate_frame(frame: pd.DataFrame) -> ValidationResult:
    normalized, mapping, structural = normalize_columns(frame)
    if structural:
        return ValidationResult([], structural, mapping, structural)
    rows: list[ValidatedRow] = []
    all_issues: list[dict[str, Any]] = []
    for index, raw in normalized.iterrows():
        source_row = int(index) + 2  # header occupies row 1
        record = {column: _clean(raw[column]) for column in CANONICAL_COLUMNS}
        issues: list[dict[str, Any]] = []
        fatal = False
        order_id = record["order_id"]
        # Core identifiers and business fields are unsafe when invalid; date/shipping gaps can be retained for correction.
        for column in ("order_id", "customer_name", "phone_number", "order_date", "order_value", "payment_type", "order_status", "assigned_employee"):
            if not record[column]:
                issues.append(_issue(source_row, order_id, column, "Missing mandatory value", f"'{column}' is empty.", "Provide a non-empty value.", "Invalid"))
                fatal = True
        if order_id and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,79}", order_id):
            issues.append(_issue(source_row, order_id, "order_id", "Invalid identifier", "Order ID contains unsupported characters.", "Use letters, numbers, hyphens, or underscores.", "Invalid"))
            fatal = True
        if record["phone_number"]:
            phone = re.sub(r"[^0-9]", "", record["phone_number"])
            if not 7 <= len(phone) <= 15:
                issues.append(_issue(source_row, order_id, "phone_number", "Invalid phone number", "Phone number must contain 7 to 15 digits.", "Correct the customer phone number.", "Invalid"))
                fatal = True
            else:
                record["phone_number"] = phone
        if record["payment_type"]:
            payment = PAYMENT_MAP.get(_key(record["payment_type"]))
            if payment not in PAYMENT_TYPES:
                issues.append(_issue(source_row, order_id, "payment_type", "Unsupported payment type", f"'{record['payment_type']}' is not Prepaid or COD.", "Use Prepaid or COD.", "Invalid"))
                fatal = True
            else:
                record["payment_type"] = payment
        if record["order_status"]:
            status = STATUS_MAP.get(_key(record["order_status"]))
            if status not in SUPPORTED_STATUSES:
                issues.append(_issue(source_row, order_id, "order_status", "Unsupported status", f"'{record['order_status']}' is unsupported.", "Use a documented supported order status.", "Invalid"))
                fatal = True
            else:
                record["order_status"] = status
        if record["order_value"]:
            try:
                amount = Decimal(record["order_value"].replace(",", "").replace("₹", ""))
                if not amount.is_finite() or amount < 0:
                    raise InvalidOperation
                record["order_value"] = format(amount.quantize(Decimal("0.01")), "f")
            except (InvalidOperation, ValueError, AttributeError):
                issues.append(_issue(source_row, order_id, "order_value", "Invalid monetary value", "Order value must be a finite non-negative number.", "Enter an INR amount such as 1299.00.", "Invalid"))
                fatal = True
        for column, is_core in (("order_date", True), ("dispatch_date", False), ("expected_delivery_date", False)):
            original = record[column]
            parsed = _parse_date(original)
            if original and not parsed:
                outcome = "Invalid" if is_core else "Needs Correction"
                issues.append(_issue(source_row, order_id, column, "Invalid date", f"'{original}' cannot be parsed as a date or timestamp.", "Use a valid ISO or Excel-compatible date.", outcome))
                if is_core:
                    fatal = True
            record[column] = parsed
        if not fatal and record["order_date"]:
            order_time = datetime.fromisoformat(record["order_date"])
            for column in ("dispatch_date", "expected_delivery_date"):
                if record[column] and datetime.fromisoformat(record[column]) < order_time:
                    record[column] = None
                    issues.append(_issue(source_row, order_id, column, "Inconsistent date sequence", f"{column} is earlier than order_date.", "Correct the date sequence.", "Needs Correction"))
        if not fatal and record["order_status"] in {"Dispatched", "Out for Delivery", "Delivered", "Delivery Failed"} and not record["dispatch_date"]:
            issues.append(_issue(source_row, order_id, "dispatch_date", "Missing rule data", "This shipment status requires a dispatch date.", "Provide the actual dispatch date.", "Needs Correction"))
        if not fatal and record["order_status"] in {"Dispatched", "Out for Delivery", "Delivery Failed"} and not record["expected_delivery_date"]:
            issues.append(_issue(source_row, order_id, "expected_delivery_date", "Missing rule data", "Expected delivery is needed to assess delivery-overdue rules.", "Provide the expected delivery date.", "Needs Correction"))
        outcome = "Invalid" if fatal else ("Needs Correction" if issues else "Valid")
        if not fatal:
            record["data_quality_status"] = outcome
        row = ValidatedRow(source_row, None if fatal else record, issues, outcome)
        rows.append(row)
        all_issues.extend(issues)
    _detect_internal_duplicates(rows, all_issues)
    return ValidationResult(rows, all_issues, mapping, structural)


def _detect_internal_duplicates(rows: list[ValidatedRow], all_issues: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[ValidatedRow]] = {}
    for row in rows:
        if row.order and row.order["order_id"]:
            grouped.setdefault(row.order["order_id"], []).append(row)
    for order_id, group in grouped.items():
        if len(group) < 2:
            continue
        fingerprints = {tuple(r.order.get(c) for c in CANONICAL_COLUMNS) for r in group if r.order}
        conflict = len(fingerprints) > 1
        for position, row in enumerate(group):
            # Keep the first exact duplicate as the candidate; quarantine every conflicting row.
            if conflict or position > 0:
                row.outcome = "Conflict" if conflict else "Duplicate"
                row.order = None
                issue = _issue(row.source_row, order_id, "order_id", "Conflicting duplicate ID" if conflict else "Exact duplicate ID",
                               "Multiple rows share this order ID with different business values." if conflict else "This row exactly duplicates an earlier row in the upload.",
                               "Correct the identifier conflict before re-uploading." if conflict else "Remove the duplicate row.",
                               row.outcome)
                row.issues.append(issue)
                all_issues.append(issue)
        if conflict:
            # The first row also becomes unsafe when another in-upload row conflicts with it.
            first = group[0]
            if first.order:
                first.order = None
                first.outcome = "Conflict"
                issue = _issue(first.source_row, order_id, "order_id", "Conflicting duplicate ID", "This order ID occurs with conflicting values in the same upload.", "Correct the conflicting records.", "Conflict")
                first.issues.append(issue)
                all_issues.append(issue)
