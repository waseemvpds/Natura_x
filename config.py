"""Central, documented configuration for the D2C operations prototype."""
from __future__ import annotations

from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATABASE_DIR = BASE_DIR / "database"
DB_PATH = DATABASE_DIR / "d2c_operations.db"
TIMEZONE = ZoneInfo("Asia/Kolkata")

SUPPORTED_STATUSES = {
    "Unconfirmed", "Confirmed", "Dispatched", "Out for Delivery", "Delivered",
    "Delivery Failed", "Cancelled", "Returned",
}
TERMINAL_STATUSES = {"Delivered", "Cancelled", "Returned"}
ACTIVE_TASK_STATUSES = {"Open", "In Progress"}
TASK_STATUSES = {"Open", "In Progress", "Resolved"}
PRIORITIES = {"High", "Medium", "Low"}
PAYMENT_TYPES = {"Prepaid", "COD"}

DEFAULT_RULES: dict[str, str] = {
    "unconfirmed_hours": "2",
    "dispatch_hours": "24",
    "high_value_threshold": "5000",
    "high_priority_deadline_hours": "4",
    "medium_priority_deadline_hours": "12",
    "low_priority_deadline_hours": "24",
    "deadline_warning_hours": "2",
}

RULE_DETAILS = {
    "UNCONFIRMED": ("Unconfirmed order", "Medium", "Confirm the order with the customer"),
    "DISPATCH_DELAY": ("Dispatch delay", "Medium", "Arrange dispatch and update the shipment details"),
    "SHIPMENT_DELAY": ("Shipment delay", "High", "Contact the courier and provide the customer with an update"),
    "FAILED_DELIVERY": ("Failed delivery", "High", "Contact the customer and arrange a new delivery attempt"),
    "HIGH_VALUE_OVERDUE": ("High-value overdue order", "High", "Escalate to operations and resolve the delivery delay"),
}

DEFAULT_EMPLOYEES = [
    ("Aarav Sharma", "Operations Executive"),
    ("Diya Patel", "Customer Support"),
    ("Kabir Singh", "Logistics Coordinator"),
    ("Meera Iyer", "Operations Manager"),
]
