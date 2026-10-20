"""Explainable, deterministic evaluation of the five business rules."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from config import RULE_DETAILS, TERMINAL_STATUSES, TIMEZONE
from database import Database


def _clock(clock: datetime | None) -> datetime:
    value = clock or datetime.now(TIMEZONE)
    return value.replace(tzinfo=TIMEZONE) if value.tzinfo is None else value.astimezone(TIMEZONE)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=TIMEZONE) if parsed.tzinfo is None else parsed.astimezone(TIMEZONE)


class RuleEngine:
    def __init__(self, database: Database):
        self.database = database

    def _settings(self) -> dict[str, Decimal]:
        return {key: Decimal(value) for key, value in self.database.get_config().items()}

    def evaluate_order(self, order: dict[str, Any], clock: datetime | None = None) -> list[dict[str, Any]]:
        """Return five transparent rule outcomes: Match, No match, or Cannot evaluate."""
        now, config, outcomes = _clock(clock), self._settings(), []
        status, order_date = order["order_status"], _dt(order.get("order_date"))
        dispatch, expected = _dt(order.get("dispatch_date")), _dt(order.get("expected_delivery_date"))
        value = Decimal(order["order_value"])

        def outcome(rule: str, state: str, explanation: str) -> None:
            details = {"rule_code": rule, "rule_name": RULE_DETAILS[rule][0], "state": state, "explanation": explanation,
                       "order_id": order["order_id"]}
            if state == "Match":
                _, priority, action = RULE_DETAILS[rule]
                details.update({"reason": explanation, "priority": priority, "action": action,
                                "assigned_employee": order["assigned_employee"]})
            outcomes.append(details)

        # Rule 1 — strict "more than", so exactly 2h is not flagged.
        if status != "Unconfirmed":
            outcome("UNCONFIRMED", "No match", "Order is not in Unconfirmed status.")
        elif not order_date:
            outcome("UNCONFIRMED", "Cannot evaluate", "Order date is missing or invalid.")
        elif now - order_date > timedelta(hours=float(config["unconfirmed_hours"])):
            outcome("UNCONFIRMED", "Match", f"Order has been unconfirmed for more than {config['unconfirmed_hours']} hours.")
        else:
            outcome("UNCONFIRMED", "No match", "Unconfirmed age has not exceeded the configured threshold.")

        # Rule 2 — confirmed and still without a dispatch date.
        if status != "Confirmed":
            outcome("DISPATCH_DELAY", "No match", "Order is not in Confirmed status.")
        elif not order_date:
            outcome("DISPATCH_DELAY", "Cannot evaluate", "Order date is missing or invalid.")
        elif dispatch:
            outcome("DISPATCH_DELAY", "No match", "A dispatch date is already recorded.")
        elif now - order_date > timedelta(hours=float(config["dispatch_hours"])):
            outcome("DISPATCH_DELAY", "Match", f"Confirmed order has not been dispatched within {config['dispatch_hours']} hours.")
        else:
            outcome("DISPATCH_DELAY", "No match", "Dispatch window has not exceeded the configured threshold.")

        # Rule 3 — only shipment states, and requires both dates for a trustworthy comparison.
        shipment_statuses = {"Dispatched", "Out for Delivery", "Delivery Failed"}
        if status not in shipment_statuses:
            outcome("SHIPMENT_DELAY", "No match", "Order is not an active dispatched shipment.")
        elif not dispatch:
            outcome("SHIPMENT_DELAY", "Cannot evaluate", "Dispatch date is missing or invalid; shipment delay cannot be measured.")
        elif not expected:
            outcome("SHIPMENT_DELAY", "Cannot evaluate", "Expected delivery date is missing or invalid; shipment delay cannot be measured.")
        elif now > expected:
            outcome("SHIPMENT_DELAY", "Match", "Expected delivery date has passed and the order is not delivered.")
        else:
            outcome("SHIPMENT_DELAY", "No match", "Expected delivery date has not passed.")

        # Rule 4 — immediate once the supported status is received.
        if status == "Delivery Failed":
            outcome("FAILED_DELIVERY", "Match", "Order status is Delivery Failed and requires immediate follow-up.")
        else:
            outcome("FAILED_DELIVERY", "No match", "Order does not have a failed delivery status.")

        # Rule 5 — strict financial boundary: exactly ₹5,000 does not qualify.
        if status in TERMINAL_STATUSES:
            outcome("HIGH_VALUE_OVERDUE", "No match", "Terminal order status is not an active undelivered order.")
        elif not expected:
            outcome("HIGH_VALUE_OVERDUE", "Cannot evaluate", "Expected delivery date is missing or invalid; overdue condition cannot be established.")
        elif value <= config["high_value_threshold"]:
            outcome("HIGH_VALUE_OVERDUE", "No match", f"Order value is not greater than ₹{config['high_value_threshold']}.")
        elif now > expected:
            outcome("HIGH_VALUE_OVERDUE", "Match", f"Order value exceeds ₹{config['high_value_threshold']} and expected delivery date has passed.")
        else:
            outcome("HIGH_VALUE_OVERDUE", "No match", "Expected delivery date has not passed.")
        return outcomes

    def reevaluate_all(self, user: str = "Rule Engine", clock: datetime | None = None) -> dict[str, int]:
        config, current = self._settings(), _clock(clock)
        matched, evaluable, created_exceptions, created_tasks = set(), set(), 0, 0
        for order in self.database.list_orders():
            for item in self.evaluate_order(order, current):
                key = (order["order_id"], item["rule_code"])
                if item["state"] != "Cannot evaluate":
                    evaluable.add(key)
                if item["state"] != "Match":
                    continue
                matched.add(key)
                exception_id, new_exception = self.database.create_or_refresh_exception(item, user=user, clock=current)
                if exception_id is None:
                    continue
                priority_key = f"{item['priority'].lower()}_priority_deadline_hours"
                deadline = (current + timedelta(hours=float(config[priority_key]))).isoformat(timespec="seconds")
                _, new_task = self.database.ensure_task(exception_id, item, deadline, user=user, clock=current)
                created_exceptions += int(new_exception)
                created_tasks += int(new_task)
        resolved = self.database.resolve_inactive_exceptions(matched, evaluable, user=user, clock=current)
        return {"matched": len(matched), "created_exceptions": created_exceptions, "created_tasks": created_tasks, "resolved": resolved}

    def explain_order(self, order_id: str, clock: datetime | None = None) -> list[dict[str, Any]]:
        order = self.database.get_order(order_id)
        if not order:
            raise ValueError("Order not found")
        return self.evaluate_order(order, clock)
