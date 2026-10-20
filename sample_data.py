"""Generate deterministic, interview-ready synthetic CSV fixtures."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from config import DATA_DIR, DEFAULT_EMPLOYEES, TIMEZONE

COLUMNS = ["Order ID", "Order Date", "Customer Name", "Phone Number", "Order Value", "Payment Type", "Order Status", "Dispatch Date", "Expected Delivery Date", "Assigned Employee"]


def _value(value: datetime | None) -> str:
    return value.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S") if value else ""


def build_sample_rows(count: int = 180, reference: datetime | None = None) -> list[dict[str, str]]:
    now = (reference or datetime.now(TIMEZONE)).replace(microsecond=0)
    employees = [name for name, _ in DEFAULT_EMPLOYEES]
    rows = []
    for i in range(1, count + 1):
        pattern = (i - 1) % 8
        order_date, dispatch, expected, value = now - timedelta(days=3), None, None, 1250 + (i % 7) * 500
        status = "Delivered"
        if pattern == 0:
            status, order_date = "Unconfirmed", now - timedelta(hours=3, minutes=i % 25)
        elif pattern == 1:
            status, order_date = "Confirmed", now - timedelta(hours=30, minutes=i % 30)
        elif pattern == 2:
            status, order_date, dispatch, expected = "Dispatched", now - timedelta(days=8), now - timedelta(days=7), now - timedelta(days=2)
        elif pattern == 3:
            status, order_date, dispatch, expected = "Delivery Failed", now - timedelta(days=6), now - timedelta(days=5), now - timedelta(days=1)
        elif pattern == 4:
            status, order_date, dispatch, expected, value = "Out for Delivery", now - timedelta(days=8), now - timedelta(days=7), now - timedelta(days=2), 7500 + i
        elif pattern == 5:
            status, order_date, dispatch, expected = "Delivered", now - timedelta(days=7), now - timedelta(days=6), now - timedelta(days=3)
        elif pattern == 6:
            status, order_date = "Confirmed", now - timedelta(hours=1)
        else:
            status, order_date, dispatch, expected = "Out for Delivery", now - timedelta(days=2), now - timedelta(days=1), now + timedelta(days=2)
        rows.append({
            "Order ID": f"ORD-{i:04d}", "Order Date": _value(order_date), "Customer Name": f"Customer {i:03d}",
            "Phone Number": f"90000{i:05d}"[-10:], "Order Value": f"{value:.2f}", "Payment Type": "Prepaid" if i % 2 else "COD",
            "Order Status": status, "Dispatch Date": _value(dispatch), "Expected Delivery Date": _value(expected),
            "Assigned Employee": employees[i % len(employees)],
        })
    return rows


def generate_sample_files(output_dir: Path = DATA_DIR, reference: datetime | None = None) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = build_sample_rows(reference=reference)
    main = output_dir / "sample_orders.csv"
    pd.DataFrame(rows, columns=COLUMNS).to_csv(main, index=False)
    updated_rows = []
    for row in rows[:24]:
        updated = row.copy()
        if updated["Order Status"] == "Confirmed":
            updated["Order Status"] = "Dispatched"
            updated["Dispatch Date"] = _value((reference or datetime.now(TIMEZONE)) - timedelta(hours=4))
            updated["Expected Delivery Date"] = _value((reference or datetime.now(TIMEZONE)) + timedelta(days=2))
        elif updated["Order Status"] == "Unconfirmed":
            updated["Order Status"] = "Confirmed"
        updated_rows.append(updated)
    updated = output_dir / "sample_orders_updated.csv"
    pd.DataFrame(updated_rows, columns=COLUMNS).to_csv(updated, index=False)
    error_rows = [
        rows[0].copy(), rows[0].copy(),
        {**rows[1], "Order ID": "ORD-CONFLICT", "Customer Name": "Anika Bose"},
        {**rows[1], "Order ID": "ORD-CONFLICT", "Customer Name": "Other Person"},
        {**rows[2], "Order ID": "ORD-BAD-DATE", "Order Date": "2026-02-30"},
        {**rows[3], "Order ID": "ORD-BAD-AMOUNT", "Order Value": "not-money"},
        {**rows[4], "Order ID": "ORD-BAD-PAYMENT", "Payment Type": "Credit"},
        {**rows[5], "Order ID": "ORD-BAD-STATUS", "Order Status": "On Hold"},
        {**rows[6], "Order ID": "ORD-NO-ORDER-DATE", "Order Date": ""},
        {**rows[7], "Order ID": "ORD-MISSING-ETA", "Expected Delivery Date": ""},
    ]
    errors = output_dir / "sample_orders_with_errors.csv"
    pd.DataFrame(error_rows, columns=COLUMNS).to_csv(errors, index=False)
    return {"sample": main, "updated": updated, "errors": errors}


if __name__ == "__main__":
    for name, path in generate_sample_files().items():
        print(f"{name}: {path}")
