"""SQLite persistence and transactional operations for the application."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from config import DB_PATH, DEFAULT_EMPLOYEES, DEFAULT_RULES, TIMEZONE


def now_iso(clock: datetime | None = None) -> str:
    value = clock or datetime.now(TIMEZONE)
    if value.tzinfo is None:
        value = value.replace(tzinfo=TIMEZONE)
    return value.astimezone(TIMEZONE).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path = DB_PATH):
        self.path = Path(path)

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        with self.connection() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS employees (
                employee_id TEXT PRIMARY KEY, employee_name TEXT NOT NULL UNIQUE,
                role TEXT NOT NULL, active_status INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY, order_date TEXT NOT NULL, customer_name TEXT NOT NULL,
                phone_number TEXT NOT NULL, order_value TEXT NOT NULL, payment_type TEXT NOT NULL,
                order_status TEXT NOT NULL, dispatch_date TEXT, expected_delivery_date TEXT,
                assigned_employee TEXT NOT NULL REFERENCES employees(employee_name),
                data_quality_status TEXT NOT NULL DEFAULT 'Valid', created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, last_imported_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(order_status);
            CREATE INDEX IF NOT EXISTS idx_orders_employee ON orders(assigned_employee);
            CREATE TABLE IF NOT EXISTS rule_config (
                config_key TEXT PRIMARY KEY, config_value TEXT NOT NULL, updated_at TEXT NOT NULL,
                updated_by TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS import_history (
                import_id TEXT PRIMARY KEY, original_filename TEXT NOT NULL, imported_at TEXT NOT NULL,
                imported_by TEXT NOT NULL, total_rows INTEGER NOT NULL, valid_rows INTEGER NOT NULL,
                needs_correction_rows INTEGER NOT NULL, invalid_rows INTEGER NOT NULL,
                duplicate_rows INTEGER NOT NULL, conflicting_rows INTEGER NOT NULL,
                inserted_orders INTEGER NOT NULL, updated_orders INTEGER NOT NULL,
                unchanged_orders INTEGER NOT NULL, rejected_rows INTEGER NOT NULL, notes TEXT
            );
            CREATE TABLE IF NOT EXISTS data_quality_issues (
                issue_id TEXT PRIMARY KEY, import_id TEXT NOT NULL REFERENCES import_history(import_id),
                source_row INTEGER, order_id TEXT, column_name TEXT NOT NULL, category TEXT NOT NULL,
                explanation TEXT NOT NULL, recommendation TEXT NOT NULL, processing_outcome TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_quality_import ON data_quality_issues(import_id);
            CREATE TABLE IF NOT EXISTS exceptions (
                exception_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id),
                rule_code TEXT NOT NULL, exception_reason TEXT NOT NULL, priority TEXT NOT NULL,
                recommended_action TEXT NOT NULL, exception_status TEXT NOT NULL,
                first_detected_at TEXT NOT NULL, last_detected_at TEXT NOT NULL, resolved_at TEXT,
                resolution_reason TEXT, occurrence_number INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(order_id, rule_code, occurrence_number)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_exception
                ON exceptions(order_id, rule_code) WHERE exception_status = 'Open';
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, exception_id TEXT NOT NULL REFERENCES exceptions(exception_id),
                order_id TEXT NOT NULL REFERENCES orders(order_id), assigned_employee TEXT NOT NULL REFERENCES employees(employee_name),
                priority TEXT NOT NULL, action_required TEXT NOT NULL, deadline TEXT NOT NULL,
                task_status TEXT NOT NULL, resolution_notes TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, resolved_at TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_task
                ON tasks(exception_id) WHERE task_status IN ('Open', 'In Progress');
            CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks(assigned_employee, task_status);
            CREATE TABLE IF NOT EXISTS audit_logs (
                audit_id TEXT PRIMARY KEY, task_id TEXT, exception_id TEXT, order_id TEXT,
                action_performed TEXT NOT NULL, previous_value TEXT, new_value TEXT,
                responsible_user TEXT NOT NULL, timestamp TEXT NOT NULL, notes TEXT,
                FOREIGN KEY(task_id) REFERENCES tasks(task_id), FOREIGN KEY(exception_id) REFERENCES exceptions(exception_id),
                FOREIGN KEY(order_id) REFERENCES orders(order_id)
            );
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp DESC);
            """)
            # Enables a safe migration for databases created by an earlier prototype version.
            exception_columns = {row["name"] for row in conn.execute("PRAGMA table_info(exceptions)")}
            if "resolution_reason" not in exception_columns:
                conn.execute("ALTER TABLE exceptions ADD COLUMN resolution_reason TEXT")
            timestamp = now_iso()
            for name, role in DEFAULT_EMPLOYEES:
                conn.execute("""INSERT OR IGNORE INTO employees(employee_id, employee_name, role, active_status, created_at)
                             VALUES (?, ?, ?, 1, ?)""", (str(uuid.uuid4()), name, role, timestamp))
            for key, value in DEFAULT_RULES.items():
                conn.execute("""INSERT OR IGNORE INTO rule_config(config_key, config_value, updated_at, updated_by)
                             VALUES (?, ?, ?, ?)""", (key, value, timestamp, "System"))

    @staticmethod
    def _dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
        return [dict(row) for row in rows]

    def audit(self, conn: sqlite3.Connection, action: str, user: str, *, task_id: str | None = None,
              exception_id: str | None = None, order_id: str | None = None, previous: Any = None,
              new: Any = None, notes: str | None = None, clock: datetime | None = None) -> None:
        stringify = lambda value: None if value is None else (json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value))
        conn.execute("""INSERT INTO audit_logs(audit_id, task_id, exception_id, order_id, action_performed,
                    previous_value, new_value, responsible_user, timestamp, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(uuid.uuid4()), task_id, exception_id, order_id, action, stringify(previous), stringify(new), user, now_iso(clock), notes))

    def get_config(self) -> dict[str, str]:
        with self.connection() as conn:
            return {r["config_key"]: r["config_value"] for r in conn.execute("SELECT config_key, config_value FROM rule_config")}

    def update_config(self, updates: dict[str, str | int | float], user: str, clock: datetime | None = None) -> None:
        with self.connection() as conn:
            for key, value in updates.items():
                old = conn.execute("SELECT config_value FROM rule_config WHERE config_key = ?", (key,)).fetchone()
                if old is None:
                    raise ValueError(f"Unknown rule setting: {key}")
                value = str(value)
                if old["config_value"] != value:
                    conn.execute("UPDATE rule_config SET config_value=?, updated_at=?, updated_by=? WHERE config_key=?",
                                 (value, now_iso(clock), user, key))
                    self.audit(conn, "Rule configuration changed", user, previous={key: old["config_value"]}, new={key: value}, clock=clock)

    def active_employees(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return self._dicts(conn.execute("SELECT * FROM employees WHERE active_status=1 ORDER BY employee_name"))

    def ensure_employee(self, conn: sqlite3.Connection, name: str, clock: datetime | None = None) -> None:
        row = conn.execute("SELECT employee_name FROM employees WHERE employee_name=?", (name,)).fetchone()
        if not row:
            conn.execute("INSERT INTO employees(employee_id,employee_name,role,active_status,created_at) VALUES(?,?,?,?,?)",
                         (str(uuid.uuid4()), name, "Imported assignee", 1, now_iso(clock)))

    def get_order(self, order_id: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
            return dict(row) if row else None

    def list_orders(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return self._dicts(conn.execute("SELECT * FROM orders ORDER BY order_date DESC, order_id"))

    def save_import_history(self, conn: sqlite3.Connection, summary: dict[str, Any], clock: datetime | None = None) -> str:
        import_id = str(uuid.uuid4())
        conn.execute("""INSERT INTO import_history VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            import_id, summary["filename"], now_iso(clock), summary["user"], summary["total_rows"], summary["valid_rows"],
            summary["needs_correction_rows"], summary["invalid_rows"], summary["duplicate_rows"], summary["conflicting_rows"],
            summary["inserted_orders"], summary["updated_orders"], summary["unchanged_orders"], summary["rejected_rows"], summary.get("notes", "")))
        return import_id

    def save_quality_issues(self, conn: sqlite3.Connection, import_id: str, issues: list[dict[str, Any]], clock: datetime | None = None) -> None:
        stamp = now_iso(clock)
        for issue in issues:
            conn.execute("""INSERT INTO data_quality_issues VALUES(?,?,?,?,?,?,?,?,?,?)""", (
                str(uuid.uuid4()), import_id, issue.get("source_row"), issue.get("order_id"), issue["column_name"],
                issue["category"], issue["explanation"], issue["recommendation"], issue["processing_outcome"], stamp))

    def import_histories(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return self._dicts(conn.execute("SELECT * FROM import_history ORDER BY imported_at DESC"))

    def quality_issues(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return self._dicts(conn.execute("""SELECT q.*, h.original_filename FROM data_quality_issues q
                                             JOIN import_history h ON h.import_id=q.import_id ORDER BY q.created_at DESC, q.source_row"""))

    def upsert_order(self, conn: sqlite3.Connection, order: dict[str, Any], clock: datetime | None = None) -> str:
        current = conn.execute("SELECT * FROM orders WHERE order_id=?", (order["order_id"],)).fetchone()
        stamp = now_iso(clock)
        fields = ("order_date", "customer_name", "phone_number", "order_value", "payment_type", "order_status", "dispatch_date", "expected_delivery_date", "assigned_employee", "data_quality_status")
        self.ensure_employee(conn, order["assigned_employee"], clock)
        if current is None:
            conn.execute(f"""INSERT INTO orders(order_id,{','.join(fields)},created_at,updated_at,last_imported_at)
                             VALUES ({','.join('?' for _ in range(len(fields)+4))})""",
                         (order["order_id"], *(order.get(f) for f in fields), stamp, stamp, stamp))
            return "inserted"
        changed = any(str(current[f] or "") != str(order.get(f) or "") for f in fields)
        if not changed:
            conn.execute("UPDATE orders SET last_imported_at=? WHERE order_id=?", (stamp, order["order_id"]))
            return "unchanged"
        assignments = ", ".join(f"{f}=?" for f in fields)
        conn.execute(f"UPDATE orders SET {assignments},updated_at=?,last_imported_at=? WHERE order_id=?",
                     (*(order.get(f) for f in fields), stamp, stamp, order["order_id"]))
        return "updated"

    def list_exceptions(self, include_resolved: bool = True) -> list[dict[str, Any]]:
        query = """SELECT e.*, o.customer_name, o.phone_number, o.order_value, o.order_status,
                          t.task_id, t.assigned_employee, t.deadline, t.task_status, t.resolution_notes
                   FROM exceptions e JOIN orders o ON o.order_id=e.order_id
                   LEFT JOIN tasks t ON t.exception_id=e.exception_id AND t.task_status IN ('Open','In Progress')"""
        if not include_resolved:
            query += " WHERE e.exception_status='Open'"
        query += " ORDER BY CASE e.priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, e.last_detected_at DESC"
        with self.connection() as conn:
            return self._dicts(conn.execute(query))

    def list_tasks(self, include_resolved: bool = True) -> list[dict[str, Any]]:
        query = """SELECT t.*, e.rule_code, e.exception_reason, e.exception_status, o.customer_name, o.phone_number,
                          o.order_value, o.order_status FROM tasks t JOIN exceptions e ON e.exception_id=t.exception_id
                   JOIN orders o ON o.order_id=t.order_id"""
        if not include_resolved:
            query += " WHERE t.task_status IN ('Open','In Progress')"
        query += " ORDER BY CASE t.priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, t.deadline"
        with self.connection() as conn:
            return self._dicts(conn.execute(query))

    def create_or_refresh_exception(self, finding: dict[str, Any], user: str = "Rule Engine", clock: datetime | None = None) -> tuple[str | None, bool]:
        stamp = now_iso(clock)
        with self.connection() as conn:
            existing = conn.execute("""SELECT * FROM exceptions WHERE order_id=? AND rule_code=? AND exception_status='Open'""",
                                    (finding["order_id"], finding["rule_code"])).fetchone()
            if existing:
                conn.execute("""UPDATE exceptions SET exception_reason=?,priority=?,recommended_action=?,last_detected_at=?,updated_at=? WHERE exception_id=?""",
                             (finding["reason"], finding["priority"], finding["action"], stamp, stamp, existing["exception_id"]))
                return existing["exception_id"], False
            prior_record = conn.execute("""SELECT exception_id, occurrence_number, resolution_reason FROM exceptions
                                          WHERE order_id=? AND rule_code=? ORDER BY occurrence_number DESC LIMIT 1""",
                                        (finding["order_id"], finding["rule_code"])).fetchone()
            # A manager can close a still-matching item after completing the follow-up. It must not re-open on
            # every unchanged import. A new occurrence is allowed only after a known false/clear state was observed.
            if prior_record and prior_record["resolution_reason"] != "Rule condition no longer matched":
                return None, False
            prior = prior_record["occurrence_number"] if prior_record else 0
            exception_id = str(uuid.uuid4())
            conn.execute("""INSERT INTO exceptions(exception_id,order_id,rule_code,exception_reason,priority,recommended_action,
                         exception_status,first_detected_at,last_detected_at,resolved_at,resolution_reason,occurrence_number,created_at,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                exception_id, finding["order_id"], finding["rule_code"], finding["reason"], finding["priority"], finding["action"],
                "Open", stamp, stamp, None, None, prior + 1, stamp, stamp))
            self.audit(conn, "Exception created", user, exception_id=exception_id, order_id=finding["order_id"], new=finding["rule_code"], clock=clock)
            return exception_id, True

    def ensure_task(self, exception_id: str, finding: dict[str, Any], deadline: str, user: str = "Rule Engine", clock: datetime | None = None) -> tuple[str, bool]:
        with self.connection() as conn:
            current = conn.execute("SELECT task_id FROM tasks WHERE exception_id=? AND task_status IN ('Open','In Progress')", (exception_id,)).fetchone()
            if current:
                return current["task_id"], False
            task_id, stamp = str(uuid.uuid4()), now_iso(clock)
            self.ensure_employee(conn, finding["assigned_employee"], clock)
            conn.execute("""INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (
                task_id, exception_id, finding["order_id"], finding["assigned_employee"], finding["priority"], finding["action"], deadline,
                "Open", None, stamp, stamp, None))
            self.audit(conn, "Task created and assigned", user, task_id=task_id, exception_id=exception_id, order_id=finding["order_id"],
                       new={"assigned_employee": finding["assigned_employee"], "deadline": deadline}, clock=clock)
            return task_id, True

    def resolve_inactive_exceptions(self, active_keys: set[tuple[str, str]], evaluable_keys: set[tuple[str, str]], user: str = "Rule Engine", clock: datetime | None = None) -> int:
        """Resolve only rules evaluated as false; missing data deliberately does not auto-resolve work."""
        resolved = 0
        with self.connection() as conn:
            rows = self._dicts(conn.execute("SELECT * FROM exceptions WHERE exception_status='Open'"))
            stamp = now_iso(clock)
            for exception in rows:
                key = (exception["order_id"], exception["rule_code"])
                if key not in active_keys and key in evaluable_keys:
                    conn.execute("UPDATE exceptions SET exception_status='Resolved',resolved_at=?,resolution_reason=?,updated_at=? WHERE exception_id=?", (stamp, "Rule condition no longer matched", stamp, exception["exception_id"]))
                    task = conn.execute("SELECT * FROM tasks WHERE exception_id=? AND task_status IN ('Open','In Progress')", (exception["exception_id"],)).fetchone()
                    if task:
                        conn.execute("UPDATE tasks SET task_status='Resolved',resolution_notes=?,resolved_at=?,updated_at=? WHERE task_id=?",
                                     ("Automatically resolved: rule condition no longer matched.", stamp, stamp, task["task_id"]))
                        self.audit(conn, "Task resolved by rule reevaluation", user, task_id=task["task_id"], exception_id=exception["exception_id"], order_id=exception["order_id"], clock=clock)
                    self.audit(conn, "Exception resolved by rule reevaluation", user, exception_id=exception["exception_id"], order_id=exception["order_id"], clock=clock)
                    resolved += 1
            # A manager-resolved task is intentionally suppressed while its rule still matches. Once a later
            # evaluation observes a known-clear condition, arm that rule for a genuinely recurring incident.
            for order_id, rule_code in evaluable_keys - active_keys:
                prior = conn.execute("""SELECT * FROM exceptions WHERE order_id=? AND rule_code=?
                                      ORDER BY occurrence_number DESC LIMIT 1""", (order_id, rule_code)).fetchone()
                if prior and prior["exception_status"] == "Resolved" and prior["resolution_reason"] != "Rule condition no longer matched":
                    conn.execute("UPDATE exceptions SET resolution_reason=?,updated_at=? WHERE exception_id=?",
                                 ("Rule condition no longer matched", stamp, prior["exception_id"]))
                    self.audit(conn, "Exception clear condition confirmed", user, exception_id=prior["exception_id"], order_id=order_id, clock=clock)
        return resolved

    def update_task(self, task_id: str, *, assigned_employee: str | None = None, task_status: str | None = None,
                    deadline: str | None = None, priority: str | None = None, resolution_notes: str | None = None,
                    user: str, clock: datetime | None = None) -> None:
        from config import PRIORITIES, TASK_STATUSES
        with self.connection() as conn:
            task = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if not task:
                raise ValueError("Task not found")
            changes: dict[str, Any] = {}
            if assigned_employee is not None and assigned_employee != task["assigned_employee"]:
                employee = conn.execute("SELECT 1 FROM employees WHERE employee_name=? AND active_status=1", (assigned_employee,)).fetchone()
                if not employee:
                    raise ValueError("Select an active employee")
                changes["assigned_employee"] = assigned_employee
            if task_status is not None:
                if task_status not in TASK_STATUSES:
                    raise ValueError("Invalid task status")
                if task_status != task["task_status"]:
                    changes["task_status"] = task_status
            if priority is not None:
                if priority not in PRIORITIES:
                    raise ValueError("Invalid priority")
                if priority != task["priority"]:
                    changes["priority"] = priority
            if deadline is not None and deadline != task["deadline"]:
                changes["deadline"] = deadline
            if resolution_notes is not None and resolution_notes != (task["resolution_notes"] or ""):
                changes["resolution_notes"] = resolution_notes
            if not changes:
                return
            stamp = now_iso(clock)
            previous = {key: task[key] for key in changes}
            if changes.get("task_status") == "Resolved":
                changes["resolved_at"] = stamp
                exception_status = conn.execute("SELECT exception_status FROM exceptions WHERE exception_id=?", (task["exception_id"],)).fetchone()["exception_status"]
                if exception_status == "Open":
                    conn.execute("UPDATE exceptions SET exception_status='Resolved',resolved_at=?,resolution_reason=?,updated_at=? WHERE exception_id=?", (stamp, "Manually resolved", stamp, task["exception_id"]))
                    self.audit(conn, "Exception resolved manually", user, exception_id=task["exception_id"], order_id=task["order_id"], clock=clock)
            elif task["task_status"] == "Resolved" and changes.get("task_status") in {"Open", "In Progress"}:
                changes["resolved_at"] = None
            assignments = ", ".join(f"{key}=?" for key in changes)
            conn.execute(f"UPDATE tasks SET {assignments},updated_at=? WHERE task_id=?", (*changes.values(), stamp, task_id))
            # Keep each operationally meaningful update independently auditable, even when a manager
            # changes several fields in a single form submission.
            common = {"task_id": task_id, "exception_id": task["exception_id"], "order_id": task["order_id"], "clock": clock}
            if "assigned_employee" in changes:
                self.audit(conn, "Task reassigned", user, previous={"assigned_employee": previous["assigned_employee"]}, new={"assigned_employee": changes["assigned_employee"]}, **common)
            if "task_status" in changes:
                status_previous = {"task_status": previous["task_status"]}
                status_new = {"task_status": changes["task_status"]}
                if "resolution_notes" in changes:
                    status_previous["resolution_notes"] = previous["resolution_notes"]
                    status_new["resolution_notes"] = changes["resolution_notes"]
                self.audit(conn, "Task status changed", user, previous=status_previous, new=status_new, **common)
            if "deadline" in changes:
                self.audit(conn, "Task deadline changed", user, previous={"deadline": previous["deadline"]}, new={"deadline": changes["deadline"]}, **common)
            if "priority" in changes:
                self.audit(conn, "Task priority changed", user, previous={"priority": previous["priority"]}, new={"priority": changes["priority"]}, **common)
            if "resolution_notes" in changes and "task_status" not in changes:
                self.audit(conn, "Task notes updated", user, previous={"resolution_notes": previous["resolution_notes"]}, new={"resolution_notes": changes["resolution_notes"]}, **common)

    def audit_logs(self) -> list[dict[str, Any]]:
        with self.connection() as conn:
            return self._dicts(conn.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC"))

    def dashboard_rows(self) -> list[dict[str, Any]]:
        return self.list_exceptions(include_resolved=False)

    def reset(self) -> None:
        if self.path.exists():
            self.path.unlink()
        self.initialize()
