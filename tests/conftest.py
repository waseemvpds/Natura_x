from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from config import TIMEZONE
from database import Database


REFERENCE = datetime(2026, 1, 20, 12, 0, tzinfo=TIMEZONE)


@pytest.fixture
def database(tmp_path):
    db = Database(tmp_path / "test_operations.db")
    db.initialize()
    return db


def order_row(order_id: str = "ORD-1001", **changes):
    values = {
        "Order ID": order_id, "Order Date": (REFERENCE - timedelta(days=2)).isoformat(), "Customer Name": "Test Customer",
        "Phone Number": "9876543210", "Order Value": "6500.00", "Payment Type": "Prepaid", "Order Status": "Confirmed",
        "Dispatch Date": "", "Expected Delivery Date": "", "Assigned Employee": "Aarav Sharma",
    }
    values.update(changes)
    return values


def write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)
    return path
