# Five-minute demonstration script

## 0:00–0:30 — Problem

“Operations used to inspect order sheets and follow up manually. This app validates uploads, produces explainable operational exceptions, assigns tasks, and keeps a permanent audit history.”

## 0:30–1:00 — Valid import

Choose **Manager — Meera Iyer**, then open **Import Orders**, choose `data/sample_orders.csv`, and click **Validate and import uploaded file**. Point out inserted/updated/unchanged counts and that the engine creates exceptions/tasks only after this explicit action. The valid fixture contains 180 synthetic orders.

## 1:00–2:00 — Automatic exceptions

Open **Dashboard**. Show all category bars and high-priority cases. Go to **Orders & Exceptions** → **Orders**, select a delivery-failed or expensive overdue order, and show the five-rule explanation table. Explain that a rule with missing input says “Cannot evaluate” instead of creating a false case.

## 2:00–3:00 — Reassign an overdue task

Open **Task Management**, select an overdue high-priority task, choose another employee, leave deadline/status unchanged, tick confirmation, and save. Show that the task ID, deadline, and status remain. Open **Reports & Audit** → **Audit trail** and show the reassignment's old/new values, manager, and timestamp.

## 3:00–4:00 — Live challenge

Upload `data/sample_orders_with_errors.csv` using the explicit import button. Show Invalid, Duplicate, Conflict, and Needs Correction findings on **Data Quality** and download its CSV. Go to **Settings & Help** → **Business rules**, change dispatch threshold from 24 to 12, confirm, save, and show its audit row plus reevaluation result.

## 4:00–5:00 — Reporting and impact

Open **Reports & Audit** → **Daily report**, expand the five categories, and download the combined CSV. Optionally switch to an employee workspace to demonstrate that it exposes only **My Dashboard**, **My Tasks**, and **Help**. Explain the time-saving measurement: compare observed manual minutes per attention-required order with the dashboard/report workflow rather than claiming an unmeasured percentage. Mention limitations: local prototype, simulated identity, no courier/WhatsApp integration.
