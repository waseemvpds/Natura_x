# Natura Ops — D2C Order Follow-up Automation

A local Streamlit prototype that converts raw D2C order files into explainable operational exceptions and auditable follow-up tasks. It is designed for a campus-placement demonstration: it runs entirely with synthetic data and needs no live courier, WhatsApp, payment, or company-system connection.

## Business problem and objective

Operations teams can lose track of unconfirmed, undispatched, delayed, and failed-delivery orders when follow-up is spread across spreadsheets and messages. Natura Ops validates incoming order data, detects actionable issues using deterministic rules, assigns work, keeps an audit trail, and produces a daily report. The objective is to centralise follow-up work and make forgotten orders visible.

## Features

- CSV and Excel order import with normalized column names.
- Row-level data-quality report for missing values, invalid dates, money, phone numbers, payment types, statuses, duplicates, and conflicts.
- SQLite persistence for orders, employees, exceptions, tasks, rules, import history, and append-only audit logs.
- All five required rule categories, stable exception identity, and duplicate-active-task prevention.
- Task status, reassignment, deadline, priority, and resolution-note updates, audited atomically.
- Dark operations dashboard with date, exception, employee, and priority filters.
- Daily CSV report covering new/unresolved exceptions, overdue tasks, high-priority cases, and employee work queues.
- Business-rule configuration through the UI, including the 24-hour to 12-hour dispatch demonstration.
- Clear simulated role workspaces: **Manager — Meera Iyer** has operational controls; employees see only their own dashboard and tasks.
- Explicit **Validate and import uploaded file** action, preventing an uploaded file from being accidentally re-imported during a page refresh.

## Technology stack

Python 3.10+, Streamlit, Pandas, SQLite, Plotly, OpenPyXL, and Pytest. Timestamps use `Asia/Kolkata`; business logic accepts an injectable reference clock for deterministic tests.

## Project structure

```text
app.py                 Streamlit interface
database.py            SQLite schema, transactions, audit operations
data_validation.py     Column normalization and row-level validation
order_import.py        CSV/Excel read, comparison, persistence
rule_engine.py         Authoritative deterministic rule engine
task_manager.py        Task-management facade
reporting.py           Dashboard/report projections
sample_data.py         Synthetic data generator
data/                  Valid, error, and update CSV samples
database/              Runtime SQLite location (not committed)
tests/                 Pytest suite
docs/                  Rules, architecture, demo, verification documentation
```

## Supported data and statuses

The import expects Order ID, Order Date, Customer Name, Phone Number, Order Value, Payment Type, Order Status, Dispatch Date, Expected Delivery Date, and Assigned Employee. Harmless case, spacing, underscore, and common name variations are recognized. Ambiguous headers are rejected rather than guessed.

Supported payment types are `Prepaid` and `COD`. Supported statuses are `Unconfirmed`, `Confirmed`, `Dispatched`, `Out for Delivery`, `Delivered`, `Delivery Failed`, `Cancelled`, and `Returned`. Cancelled and Returned orders are terminal and are not treated as active undelivered orders.

## Business rules and assumptions

| Rule | Trigger | Default priority |
|---|---|---|
| Unconfirmed | `Unconfirmed` for strictly more than 2 hours from order date | Medium |
| Dispatch delay | `Confirmed`, no dispatch date, strictly more than 24 hours from order date | Medium |
| Shipment delay | Active dispatched shipment, dispatch date present, expected delivery date passed | High |
| Failed delivery | `Delivery Failed` status | High |
| High-value overdue | Non-terminal order, amount strictly greater than ₹5,000, expected delivery date passed | High |

The UI can configure the two time thresholds, high-value threshold, priority SLAs, and approaching-deadline warning interval. An active exception has a stable `(order_id, rule_code)` identity and one active task. Repeated imports/rule runs refresh detection timestamps without duplicating active work. A status/date update that clears a rule automatically resolves its active exception/task; missing information never creates a new operational exception.

## Validation and import behaviour

Core identity/business errors (for example blank ID, invalid amount, unsupported status, invalid payment type, invalid order date) are rejected. Shipping-data gaps such as a missing expected date on a dispatched order are stored as `Needs Correction` when the rest of the order is safe; rules needing the missing data are shown as `Cannot evaluate` rather than guessed. Exact in-upload duplicates retain the first row and reject later copies. Conflicting IDs in the same upload quarantine all conflicting records. Across uploads, customer name, normalized phone, and payment type are immutable identity fields; matching identity permits a deterministic status/date/value update while preserving task history.

## Database and audit design

The database is created safely at `database/d2c_operations.db` on first run and is never automatically erased. Foreign keys, transaction boundaries, unique indexes, and parameterized SQL protect integrity. A task reassignment/status/deadline update and its audit event use the same transaction. The prototype uses a sidebar simulated-user selector; it is explicitly not production authentication.

Historical audit entries have no edit/delete controls in the application. They record task/exception/order identifiers where relevant, old/new values, responsible simulated user, timestamp, and action. If a manager changes assignment, status, deadline, priority, or notes in one save, each meaningful change receives its own audit entry. Import history explains inserted, updated, unchanged, invalid, duplicate, and conflict outcomes.

## Manager and employee workspaces

Choose a workspace from the sidebar. The displayed role is intentional:

| Workspace | What it can access |
|---|---|
| **Manager — Meera Iyer** | Dashboard, imports, data quality, all orders/exceptions, all tasks, reports, audit trail, rule settings, and safe demo reset. Managers may reassign work or change deadlines/priorities. |
| **Employee — [name]** | My Dashboard, My Tasks, and Help. Employees see only their own assigned tasks and can update their task status and notes. |

An employee cannot reassign work, alter deadlines/priorities, upload orders, see other employees' workloads, change rules, or reset demonstration data through the UI. This is a deliberate prototype UI restriction; it is not a substitute for production authentication and authorization.

## Installation and startup on Windows PowerShell

From the project directory:

```powershell
Set-Location "D:\Natura x"
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python sample_data.py
streamlit run app.py
```

Then open the local address shown by Streamlit (normally `http://localhost:8501`). The app initializes an empty persistent database. Choose **Manager — Meera Iyer**, open **Import Orders**, select `data/sample_orders.csv`, then click **Validate and import uploaded file**.

Run the full test suite with:

```powershell
python -m pytest -q
```

## Sample data

- `data/sample_orders.csv` — 180 valid synthetic orders covering all operational states.
- `data/sample_orders_with_errors.csv` — missing date, invalid date/money/type/status, exact duplicate, conflict, and missing ETA cases.
- `data/sample_orders_updated.csv` — legitimate updates to a subset of valid orders.

Recreate those files at any time with `python sample_data.py`.

## Safe demo reset

Choose **Manager — Meera Iyer**, open **Settings & Help** → **Help and demo reset**, type exactly `RESET DEMO`, and press **Reset database and load valid sample data**. This explicitly deletes only `database/d2c_operations.db`, then recreates it and imports the valid sample data. It does not delete the CSV fixtures. Do not manually delete a database you need to preserve.

## Five-minute demonstration

Use [docs/demo_script.md](docs/demo_script.md) for a timed walkthrough. In short: import the valid sample, show rule explanations and high-priority cases, reassign an overdue task and show the audit record, import the error sample, change dispatch from 24 to 12 hours, and download the report.

## Business impact and limitations

For a transparent time-saving estimate, measure the number of attention-required orders and multiply by the observed manual lookup/follow-up minutes per order before deployment; compare it with the dashboard/report workflow after deployment. This project does not claim an unmeasured percentage reduction. It is a local prototype without authentication/authorization, row-level conflict resolution workflow, production concurrency controls, live courier feeds, notifications, or a production backup/retention policy.

See [docs/business_rules.md](docs/business_rules.md), [docs/technical_overview.md](docs/technical_overview.md), and [docs/requirements_verification.md](docs/requirements_verification.md) for details.
