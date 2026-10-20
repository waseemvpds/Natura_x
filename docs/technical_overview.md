# Technical overview

## Architecture

`app.py` is a thin Streamlit presentation layer. It invokes `order_import.py` for file processing, `data_validation.py` for deterministic validation, `rule_engine.py` for all business decisions, `database.py` for persistence/transactions, and `reporting.py` for report projections. Tests exercise these layers without launching Streamlit. The presentation layer deliberately separates manager and employee workspaces to keep the employee experience focused.

## Data relationships

```text
employees ──< orders ──< exceptions ──< tasks
                   │          │             │
                   └──────────┴─────────────┴──< audit_logs
import_history ──< data_quality_issues
rule_config (independent persisted settings)
```

Orders store the latest known valid-safe state. Exceptions retain occurrence numbers, detection timestamps, status, reason, action, and priority. Tasks retain assignment, status, deadline, and notes. Import history and quality issues retain what was received, including rejected rows. Database operations use SQLite foreign keys, transactions, parameter binding, indexes, and unique partial indexes.

## Import/update policy

Column aliases become one canonical schema. Missing or ambiguous headers stop the file safely. Per-row core validation prevents invalid IDs, money, dates, type, status, or identifiers from entering the orders table. Across uploads, the customer identity tuple (name, normalized phone, payment type) must match an existing ID. When it matches, changed status/dates/value are an update—not a new order—and no task/audit history is removed.

## Exception/task lifecycle

1. A manager explicitly submits an uploaded file with **Validate and import uploaded file**. The validated import is committed with import history and quality issues; an ordinary Streamlit rerun does not import it again.
2. The rule engine evaluates every stored order using persisted configuration.
3. A matching new rule creates an open exception and task in separate transactional operations; repeated evaluations find the stable active records instead.
4. A manager may reassign, reprioritize, alter a deadline, progress, or resolve a task. Employees see only their own tasks and can change only task status and notes. Reassignment keeps its ID, status, and deadline unless the manager explicitly changes them.
5. Each task/configuration/lifecycle action creates an audit log in the same transaction as its underlying change. A combined manager update produces separate audit entries for assignment, status, deadline, priority, and notes where applicable.
6. A known-false rule automatically closes active work; `Cannot evaluate` preserves existing work rather than asserting a false resolution.

## Security scope

This assessment prototype does not authenticate real users. The selector intentionally labels **Manager — Meera Iyer** and employees, and the Streamlit interface limits pages/actions accordingly, but this is only a clear audit-attribution and usability simulation. A production deployment would need server-enforced identity, permissions, secrets management, encryption/backups, concurrency controls, monitoring, retention policies, and integrations.
