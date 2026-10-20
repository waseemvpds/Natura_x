"""Streamlit entry point for the D2C Order Follow-up Automation System."""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

from config import DATA_DIR, DB_PATH, PRIORITIES, TASK_STATUSES, TIMEZONE
from database import Database
from order_import import import_orders
from reporting import combined_report_csv, daily_report, task_is_approaching, task_is_overdue
from rule_engine import RuleEngine
from sample_data import generate_sample_files


TASK_STATUS_OPTIONS = ["Open", "In Progress", "Resolved"]


st.set_page_config(page_title="Natura Ops | Order Follow-up", page_icon="◈", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
    .stApp { background: #0b1220; color: #e5edf8; }
    [data-testid="stSidebar"] { background: #101a2d; border-right: 1px solid #263552; }
    [data-testid="stMetric"] { background: #131f34; border: 1px solid #273957; border-radius: 14px; padding: 18px; }
    [data-testid="stMetricLabel"] { color: #9fb1cb; } [data-testid="stMetricValue"] { color: #f3f7ff; }
    .brand { padding: 0 4px 10px; } .brand h2 { color: #f3f7ff; margin-bottom: 0; }
    .brand p { color: #84a0c5; font-size: .84rem; margin-top: 3px; }
    .badge { display:inline-block; border-radius:999px; padding:3px 9px; margin-right:5px; font-size:.75rem; font-weight:700; }
    .high { background:#5f1d2d; color:#ffbec9; } .medium { background:#5a4519; color:#ffe199; } .low { background:#173e50; color:#a9e5ff; }
    .notice { background: #102b3d; padding: 12px 16px; border-radius: 10px; border-left: 3px solid #45b7d6; }
    div[data-testid="stDataFrame"] { border: 1px solid #273957; border-radius: 8px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource
def get_database() -> Database:
    database = Database(DB_PATH)
    database.initialize()
    return database


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _download(frame: pd.DataFrame, label: str, filename: str) -> None:
    st.download_button(label, frame.to_csv(index=False).encode("utf-8"), file_name=filename, mime="text/csv", use_container_width=True)


def _priority_badge(priority: str) -> str:
    return f'<span class="badge {priority.lower()}">{priority}</span>'


def sidebar(database: Database) -> tuple[str, str, bool]:
    st.sidebar.markdown("<div class='brand'><h2>◈ Natura Ops</h2><p>Order follow-up control centre</p></div>", unsafe_allow_html=True)
    people = database.active_employees()
    people_by_name = {person["employee_name"]: person for person in people}
    names = list(people_by_name)

    def person_label(name: str) -> str:
        person = people_by_name[name]
        return f"Manager — {name}" if "Manager" in person["role"] else f"Employee — {name}"

    user = st.sidebar.selectbox(
        "Choose workspace",
        names,
        index=next((index for index, name in enumerate(names) if "Manager" in people_by_name[name]["role"]), 0),
        format_func=person_label,
        help="Prototype role selector only; this is not production authentication.",
    )
    is_manager = "Manager" in people_by_name[user]["role"]
    st.sidebar.success("Manager workspace" if is_manager else "Employee workspace")
    pages = (
        ["Dashboard", "Import Orders", "Data Quality", "Orders & Exceptions", "Task Management", "Reports & Audit", "Settings & Help"]
        if is_manager
        else ["My Dashboard", "My Tasks", "Help"]
    )
    page = st.sidebar.radio("Navigate", pages, label_visibility="collapsed")
    st.sidebar.caption("Operational timestamps use Asia/Kolkata time.")
    return page, user, is_manager


def get_dashboard_data(database: Database, user: str, is_manager: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return only the data that the selected workspace is allowed to see."""
    orders = _frame(database.list_orders())
    exceptions = _frame(database.list_exceptions(include_resolved=False))
    tasks = _frame(database.list_tasks(include_resolved=False))
    if orders.empty:
        st.info("No orders are loaded yet. Import the sample data or upload an order file.")
        return orders, exceptions, tasks
    if not is_manager:
        tasks = tasks[tasks["assigned_employee"] == user] if not tasks.empty else tasks
        exception_ids = set(tasks["exception_id"]) if not tasks.empty else set()
        order_ids = set(tasks["order_id"]) if not tasks.empty else set()
        exceptions = exceptions[exceptions["exception_id"].isin(exception_ids)] if not exceptions.empty else exceptions
        orders = orders[orders["order_id"].isin(order_ids)]
        return orders, exceptions, tasks

    orders["order_date_parsed"] = pd.to_datetime(orders["order_date"], errors="coerce")
    start, end = orders["order_date_parsed"].min().date(), orders["order_date_parsed"].max().date()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        dates = st.date_input("Order date", value=(start, end), min_value=start, max_value=end)
    with col2:
        types = ["All"] + (sorted(exceptions["rule_code"].unique().tolist()) if not exceptions.empty else [])
        exception_type = st.selectbox("Exception type", types)
    with col3:
        assignee = st.selectbox("Employee", ["All"] + [e["employee_name"] for e in database.active_employees()])
    with col4:
        priority = st.selectbox("Priority", ["All", "High", "Medium", "Low"])
    if isinstance(dates, tuple) and len(dates) == 2:
        orders = orders[(orders["order_date_parsed"].dt.date >= dates[0]) & (orders["order_date_parsed"].dt.date <= dates[1])]
    allowed = set(orders["order_id"])
    if not exceptions.empty:
        exceptions = exceptions[exceptions["order_id"].isin(allowed)]
        if exception_type != "All":
            exceptions = exceptions[exceptions["rule_code"] == exception_type]
        if assignee != "All":
            exceptions = exceptions[exceptions["assigned_employee"] == assignee]
        if priority != "All":
            exceptions = exceptions[exceptions["priority"] == priority]
    # All KPI cards and charts use the same active filter scope. When an exception-specific
    # filter is selected, "Orders uploaded" means the orders represented by that filtered work.
    if exception_type != "All" or assignee != "All" or priority != "All":
        orders = orders[orders["order_id"].isin(set(exceptions["order_id"]))]
    if not tasks.empty:
        tasks = tasks[tasks["order_id"].isin(set(orders["order_id"]))]
        tasks = tasks[tasks["exception_id"].isin(set(exceptions["exception_id"]))] if not exceptions.empty else tasks.iloc[0:0]
    return orders, exceptions, tasks


def render_dashboard(database: Database, user: str, is_manager: bool) -> None:
    st.title("Operations Dashboard" if is_manager else "My Dashboard")
    st.caption("Monitor follow-up work that needs attention." if is_manager else "Only tasks assigned to you are shown here.")
    orders, exceptions, tasks = get_dashboard_data(database, user, is_manager)
    now = datetime.now(TIMEZONE)
    overdue_count = int(tasks.apply(lambda item: task_is_overdue(item.to_dict(), now), axis=1).sum()) if not tasks.empty else 0
    high_count = int((exceptions["priority"] == "High").sum()) if not exceptions.empty else 0
    open_count = int((tasks["task_status"] == "Open").sum()) if not tasks.empty else 0
    progress_count = int((tasks["task_status"] == "In Progress").sum()) if not tasks.empty else 0
    k1, k2, k3, k4, k5 = st.columns(5)
    if is_manager:
        k1.metric("Orders in view", len(orders))
        k2.metric("Attention cases", len(exceptions))
    else:
        k1.metric("My active tasks", len(tasks))
        k2.metric("My open tasks", open_count)
    k3.metric("In progress", progress_count)
    k4.metric("Overdue", overdue_count)
    k5.metric("High priority", high_count)
    if exceptions.empty:
        st.success("You have no active follow-up work." if not is_manager else "No active exceptions match the selected filters.")
        return
    left, right = st.columns((1, 1))
    with left:
        by_rule = exceptions.groupby("rule_code", as_index=False).size().rename(columns={"size": "Exceptions"})
        fig = px.bar(by_rule, x="rule_code", y="Exceptions", color="rule_code", title="Exceptions by category", color_discrete_sequence=["#4db8ff", "#f0b44b", "#f1707b", "#956cff", "#5ac8a8"])
        fig.update_layout(template="plotly_dark", showlegend=False, paper_bgcolor="#131f34", plot_bgcolor="#131f34", margin=dict(l=10, r=10, t=45, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with right:
        if is_manager:
            work = tasks.groupby("assigned_employee", as_index=False).size().rename(columns={"size": "Pending tasks"}) if not tasks.empty else pd.DataFrame(columns=["assigned_employee", "Pending tasks"])
            fig = px.bar(work, x="assigned_employee", y="Pending tasks", title="Employee-wise pending tasks", color_discrete_sequence=["#4db8ff"])
        else:
            work = tasks.groupby("priority", as_index=False).size().rename(columns={"size": "Tasks"}) if not tasks.empty else pd.DataFrame(columns=["priority", "Tasks"])
            fig = px.bar(work, x="priority", y="Tasks", title="My tasks by priority", color_discrete_sequence=["#4db8ff"])
        fig.update_layout(template="plotly_dark", paper_bgcolor="#131f34", plot_bgcolor="#131f34", margin=dict(l=10, r=10, t=45, b=10))
        st.plotly_chart(fig, use_container_width=True)
    st.subheader("High-priority cases" if is_manager else "My high-priority cases")
    show = exceptions[exceptions["priority"] == "High"].copy()
    if show.empty:
        st.caption("No high-priority cases under the current filters.")
    else:
        st.dataframe(show[["exception_id", "order_id", "customer_name", "rule_code", "exception_reason", "priority", "assigned_employee", "deadline", "task_status"]], use_container_width=True, hide_index=True)
    warning = float(database.get_config()["deadline_warning_hours"])
    near = tasks[tasks.apply(lambda item: task_is_approaching(item.to_dict(), warning, now), axis=1)] if not tasks.empty else tasks
    if not near.empty:
        st.warning(f"{len(near)} task(s) are due within the configured {warning:g}-hour warning interval.")


def render_import(database: Database, user: str) -> None:
    st.title("Import Orders")
    st.markdown("Upload a CSV or Excel file, then choose **Validate and import**. Problematic rows are never silently discarded.")
    uploaded = st.file_uploader("Order file", type=["csv", "xlsx", "xls"], help="Expected fields: the ten assignment-required order columns.")
    source: object | None = None
    filename = ""
    if uploaded and st.button("Validate and import uploaded file", type="primary", use_container_width=True):
        source, filename = BytesIO(uploaded.getvalue()), uploaded.name
    sample_path = DATA_DIR / "sample_orders.csv"
    if st.button("Load valid sample data", use_container_width=True):
        source, filename = sample_path, sample_path.name
    if source is not None:
        try:
            result = import_orders(database, source, filename, user)
            summary = result["summary"]
            st.success(f"Import completed: {summary['inserted_orders']} inserted, {summary['updated_orders']} updated, {summary['unchanged_orders']} unchanged.")
            st.dataframe(_frame([summary]).T.rename(columns={0: "Value"}), use_container_width=True)
            issues = _frame(result["issues"])
            if not issues.empty:
                st.warning(f"{len(issues)} data-quality finding(s) were retained for review.")
                st.dataframe(issues, use_container_width=True, hide_index=True)
                _download(issues, "Download this data-quality report", f"quality_{filename}.csv")
            if result["rule_result"]:
                st.info("Rule engine reevaluated orders: " + ", ".join(f"{key.replace('_', ' ')} {value}" for key, value in result["rule_result"].items()))
        except Exception as exc:
            st.error(f"Import was not completed: {exc}")


def render_quality(database: Database) -> None:
    st.title("Data Quality")
    st.caption("Rows are classified as Valid, Needs Correction, Invalid, Duplicate, or Conflict. Only safely identifiable records can be imported.")
    issues = _frame(database.quality_issues())
    history = _frame(database.import_histories())
    if not history.empty:
        st.subheader("Import comparison history")
        st.dataframe(history, use_container_width=True, hide_index=True)
    if issues.empty:
        st.success("No data-quality issues have been recorded yet.")
    else:
        st.subheader("Row-level findings")
        st.dataframe(issues, use_container_width=True, hide_index=True)
        _download(issues, "Download all data-quality findings", "data_quality_report.csv")


def render_orders(database: Database) -> None:
    st.subheader("Orders")
    orders = _frame(database.list_orders())
    if orders.empty:
        st.info("Import orders to inspect them here.")
        return
    st.dataframe(orders, use_container_width=True, hide_index=True)
    selected = st.selectbox("Inspect an order", orders["order_id"].tolist())
    order = database.get_order(selected)
    st.subheader(f"Rule explanation — {selected}")
    st.dataframe(_frame(RuleEngine(database).explain_order(selected)), use_container_width=True, hide_index=True)
    customer_orders = orders[orders["phone_number"] == order["phone_number"]]
    if len(customer_orders) > 1:
        st.caption("Other orders with the same normalized phone number (not automatically merged):")
        st.dataframe(customer_orders, use_container_width=True, hide_index=True)


def render_exceptions(database: Database) -> None:
    st.subheader("Exceptions")
    exceptions = _frame(database.list_exceptions(include_resolved=True))
    if exceptions.empty:
        st.success("No exceptions have been generated yet.")
        return
    active = exceptions[exceptions["exception_status"] == "Open"]
    st.metric("Active exceptions", len(active))
    st.dataframe(exceptions, use_container_width=True, hide_index=True)
    st.caption("Every active exception has one active task. Resolved records remain available as history, and a recurring incident opens a new occurrence.")


def render_tasks(database: Database, user: str, is_manager: bool) -> None:
    st.title("Task Management" if is_manager else "My Tasks")
    st.caption("Managers can assign and reprioritize work. Employees can update only their own task progress and notes." if is_manager else "Update the progress and notes for tasks assigned to you.")
    tasks = _frame(database.list_tasks(include_resolved=True))
    if not is_manager and not tasks.empty:
        tasks = tasks[tasks["assigned_employee"] == user]
    if tasks.empty:
        st.info("You do not have any assigned tasks yet." if not is_manager else "Tasks will appear after an exception is detected.")
        return
    now = datetime.now(TIMEZONE)
    tasks["overdue"] = tasks.apply(lambda row: task_is_overdue(row.to_dict(), now), axis=1)
    table_columns = ["order_id", "customer_name", "rule_code", "exception_reason", "priority", "action_required", "assigned_employee", "deadline", "task_status", "overdue"]
    st.dataframe(tasks[[column for column in table_columns if column in tasks]], use_container_width=True, hide_index=True)
    editable = tasks[tasks["task_status"].isin(["Open", "In Progress"])]
    if editable.empty:
        st.caption("There are no active tasks to update." if is_manager else "You have no active tasks to update.")
        return
    task_labels = {row["task_id"]: f"{row['order_id']} — {row['rule_code']} ({row['priority']})" for _, row in editable.iterrows()}
    selected_id = st.selectbox("Select a task", list(task_labels), format_func=task_labels.get)
    task = editable[editable["task_id"] == selected_id].iloc[0].to_dict()
    st.markdown(f"Task for **{task['order_id']}** — {task['customer_name']} &nbsp; {_priority_badge(task['priority'])}", unsafe_allow_html=True)
    due = datetime.fromisoformat(task["deadline"]).astimezone(TIMEZONE)
    with st.form("task_update_form"):
        if is_manager:
            employees = [item["employee_name"] for item in database.active_employees()]
            a, b, c = st.columns(3)
            assigned = a.selectbox("Assigned employee", employees, index=employees.index(task["assigned_employee"]))
            status = b.selectbox("Task status", TASK_STATUS_OPTIONS, index=TASK_STATUS_OPTIONS.index(task["task_status"]))
            priority = c.selectbox("Priority", ["High", "Medium", "Low"], index=["High", "Medium", "Low"].index(task["priority"]))
            d, e = st.columns(2)
            due_date = d.date_input("Deadline date", due.date())
            due_time = e.time_input("Deadline time", due.time().replace(tzinfo=None))
        else:
            assigned = task["assigned_employee"]
            priority = task["priority"]
            due_date, due_time = due.date(), due.time().replace(tzinfo=None)
            status = st.selectbox("Task status", TASK_STATUS_OPTIONS, index=TASK_STATUS_OPTIONS.index(task["task_status"]))
            st.caption(f"Deadline: {due.strftime('%d %b %Y, %I:%M %p')} · Priority: {task['priority']}")
        notes = st.text_area("Resolution / update notes", value=task.get("resolution_notes") or "", placeholder="Required context when resolving a task.")
        confirmed = st.checkbox("I confirm this task update")
        submitted = st.form_submit_button("Save task update", use_container_width=True)
    if submitted:
        if not confirmed:
            st.error("Confirm the update before saving.")
        elif status == "Resolved" and not notes.strip():
            st.error("Add a short resolution note before resolving a task.")
        else:
            deadline = datetime.combine(due_date, due_time, tzinfo=TIMEZONE).isoformat(timespec="seconds")
            try:
                database.update_task(
                    selected_id,
                    assigned_employee=assigned if is_manager else None,
                    task_status=status,
                    priority=priority if is_manager else None,
                    deadline=deadline if is_manager else None,
                    resolution_notes=notes,
                    user=user,
                )
                st.success("Task updated and audit entry recorded." if not is_manager else "Task updated and audit entry recorded. Reassignment does not reset task ID, status, or deadline unless you explicitly changed them.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))


def render_reports(database: Database) -> None:
    st.subheader("Daily Exception Report")
    reports = daily_report(database)
    st.download_button("Download complete daily CSV report", combined_report_csv(reports), file_name="daily_exception_report.csv", mime="text/csv", use_container_width=True)
    for title, report in reports.items():
        with st.expander(f"{title} ({len(report)})", expanded=title == "Unresolved exceptions"):
            if report.empty:
                st.caption("No records in this report category.")
            else:
                st.dataframe(report, use_container_width=True, hide_index=True)
                _download(report, f"Download {title.lower()} CSV", f"{title.lower().replace(' ', '_')}.csv")


def render_audit(database: Database) -> None:
    st.subheader("Audit Trail")
    st.caption("Audit entries are append-only through the application interface and persist across restarts.")
    logs = _frame(database.audit_logs())
    if logs.empty:
        st.info("No auditable actions have been recorded yet.")
    else:
        st.dataframe(logs, use_container_width=True, hide_index=True)
        _download(logs, "Download audit CSV", "audit_trail.csv")


def render_rules(database: Database, user: str) -> None:
    st.subheader("Business Rules")
    st.markdown("Threshold changes are stored in SQLite and audit-logged. Reevaluation preserves any existing active task rather than generating a duplicate.")
    config = database.get_config()
    with st.form("rule_config"):
        c1, c2, c3 = st.columns(3)
        unconfirmed = c1.number_input("Unconfirmed threshold (hours)", min_value=0.1, value=float(config["unconfirmed_hours"]), step=0.5)
        dispatch = c2.number_input("Dispatch threshold (hours)", min_value=0.1, value=float(config["dispatch_hours"]), step=1.0)
        high_value = c3.number_input("High-value threshold (₹)", min_value=0.0, value=float(config["high_value_threshold"]), step=500.0)
        c4, c5, c6 = st.columns(3)
        high_sla = c4.number_input("High priority SLA (hours)", min_value=0.1, value=float(config["high_priority_deadline_hours"]), step=0.5)
        medium_sla = c5.number_input("Medium priority SLA (hours)", min_value=0.1, value=float(config["medium_priority_deadline_hours"]), step=0.5)
        warning = c6.number_input("Deadline warning interval (hours)", min_value=0.1, value=float(config["deadline_warning_hours"]), step=0.5)
        confirm = st.checkbox("I confirm the rule configuration change and reevaluation")
        save = st.form_submit_button("Save and reevaluate orders", use_container_width=True)
    if save:
        if not confirm:
            st.error("Confirm the configuration change first.")
        else:
            updates = {"unconfirmed_hours": unconfirmed, "dispatch_hours": dispatch, "high_value_threshold": high_value,
                       "high_priority_deadline_hours": high_sla, "medium_priority_deadline_hours": medium_sla, "deadline_warning_hours": warning}
            database.update_config(updates, user)
            result = RuleEngine(database).reevaluate_all(user=user)
            st.success("Configuration saved. " + ", ".join(f"{key.replace('_', ' ')}: {value}" for key, value in result.items()))
    st.dataframe(pd.DataFrame([{"Rule": "UNCONFIRMED", "Logic": "Unconfirmed longer than configured hours"}, {"Rule": "DISPATCH_DELAY", "Logic": "Confirmed, no dispatch, longer than configured hours"}, {"Rule": "SHIPMENT_DELAY", "Logic": "Dispatched expected date passed without delivery"}, {"Rule": "FAILED_DELIVERY", "Logic": "Delivery Failed status"}, {"Rule": "HIGH_VALUE_OVERDUE", "Logic": "Value strictly > configured threshold and expected date passed"}]), use_container_width=True, hide_index=True)


def render_help(database: Database, user: str) -> None:
    st.subheader("About and safe demo reset")
    st.markdown("""<div class='notice'>This local prototype uses simulated users and synthetic data. It does not connect to payment gateways, couriers, WhatsApp, or production order systems.</div>""", unsafe_allow_html=True)
    st.subheader("Quick start")
    st.markdown("1. Import `data/sample_orders.csv` from <b>Import Orders</b>.<br>2. Review exceptions in <b>Orders & Exceptions</b> and tasks in <b>Task Management</b>.<br>3. Reassign an overdue task and open <b>Reports & Audit</b> → <b>Audit trail</b>.<br>4. Change dispatch threshold from 24 to 12 hours in <b>Settings & Help</b> → <b>Business rules</b>.<br>5. Download the report from <b>Reports & Audit</b> → <b>Daily report</b>.", unsafe_allow_html=True)
    st.subheader("Safe demo reset")
    st.warning("Reset deletes only this application's SQLite database, including imported orders, tasks, reports, and audits. Sample CSV files are not deleted.")
    with st.form("reset_form"):
        phrase = st.text_input("Type RESET DEMO to enable reset")
        reset = st.form_submit_button("Reset database and load valid sample data")
    if reset:
        if phrase != "RESET DEMO":
            st.error("The confirmation phrase did not match; no data was changed.")
        else:
            database.reset()
            path = DATA_DIR / "sample_orders.csv"
            import_orders(database, path, path.name, user)
            st.success("Database was reset and the valid sample data was imported.")
            st.rerun()
    st.caption("Full setup, rule, architecture, and demonstration documentation is available in README.md and docs/.")


def render_orders_and_exceptions(database: Database) -> None:
    st.title("Orders & Exceptions")
    orders_tab, exceptions_tab = st.tabs(["Orders", "Exceptions"])
    with orders_tab:
        render_orders(database)
    with exceptions_tab:
        render_exceptions(database)


def render_reports_and_audit(database: Database) -> None:
    st.title("Reports & Audit")
    reports_tab, audit_tab = st.tabs(["Daily report", "Audit trail"])
    with reports_tab:
        render_reports(database)
    with audit_tab:
        render_audit(database)


def render_settings_and_help(database: Database, user: str) -> None:
    st.title("Settings & Help")
    rules_tab, help_tab = st.tabs(["Business rules", "Help and demo reset"])
    with rules_tab:
        render_rules(database, user)
    with help_tab:
        render_help(database, user)


def render_employee_help() -> None:
    st.title("Help")
    st.markdown("""<div class='notice'>Your workspace shows only tasks assigned to you. Open <b>My Tasks</b>, complete the follow-up, add a useful note, and update the task status.</div>""", unsafe_allow_html=True)
    st.subheader("What each task status means")
    st.markdown("- **Open** — work has not started yet.\n- **In Progress** — you are actively following up.\n- **Resolved** — the required action is complete; add a short resolution note.")
    st.subheader("Need a change?")
    st.caption("Ask a manager to reassign a task, change its priority, alter its deadline, import orders, or change business rules.")


def main() -> None:
    generate_sample_files()
    database = get_database()
    page, user, is_manager = sidebar(database)
    renderers = (
        {
            "Dashboard": lambda: render_dashboard(database, user, True),
            "Import Orders": lambda: render_import(database, user),
            "Data Quality": lambda: render_quality(database),
            "Orders & Exceptions": lambda: render_orders_and_exceptions(database),
            "Task Management": lambda: render_tasks(database, user, True),
            "Reports & Audit": lambda: render_reports_and_audit(database),
            "Settings & Help": lambda: render_settings_and_help(database, user),
        }
        if is_manager
        else {
            "My Dashboard": lambda: render_dashboard(database, user, False),
            "My Tasks": lambda: render_tasks(database, user, False),
            "Help": render_employee_help,
        }
    )
    renderers[page]()


if __name__ == "__main__":
    main()
