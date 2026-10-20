# Business rules

## Shared policy

The operational clock is Asia/Kolkata. The testable evaluator receives an explicit reference clock. All threshold checks are strict: an order at exactly 2 hours is not unconfirmed-overdue; an order at exactly 24 hours is not dispatch-overdue; an order worth exactly ₹5,000 is not high value.

| Code | Evaluation | Cannot evaluate when | Priority / action |
|---|---|---|---|
| `UNCONFIRMED` | Status is Unconfirmed and now − order date is > configured unconfirmed hours | order date invalid/missing | Medium / confirm with customer |
| `DISPATCH_DELAY` | Status is Confirmed, no dispatch date, now − order date is > dispatch hours | order date invalid/missing | Medium / arrange dispatch |
| `SHIPMENT_DELAY` | Status is Dispatched, Out for Delivery, or Delivery Failed; dispatch date exists; expected date is before now | dispatch or expected date invalid/missing | High / contact courier and customer |
| `FAILED_DELIVERY` | Status is Delivery Failed | never, once supported status is known | High / arrange a new attempt |
| `HIGH_VALUE_OVERDUE` | Status is non-terminal, value is strictly above configured value, expected date is before now | expected date invalid/missing | High / escalate to operations |

`Delivered`, `Cancelled`, and `Returned` are terminal. Rule outcomes are displayed order by order as Match, No match, or Cannot evaluate so a manager can see why a case exists or does not exist.

## Lifecycle and duplicate prevention

An exception has a stable rule/category identity, with a database partial unique index that permits only one open `(order_id, rule_code)` exception. Each open exception gets at most one active task by a second partial unique index. Running rules repeatedly refreshes the existing exception without replacing its task or deadline.

When an evaluated rule becomes false, its active exception and task are automatically resolved and audited. If required data is missing, the engine deliberately does not auto-resolve existing work because it cannot establish that the incident is gone. Imported orders with a missing required rule input are marked Needs Correction; a new operational task is never invented from missing data.

## Configurable values

Default configuration: unconfirmed 2 hours, dispatch 24 hours, high value ₹5,000, high SLA 4 hours, medium SLA 12 hours, low SLA 24 hours, and deadline warning 2 hours. The Manager workspace's **Settings & Help** → **Business rules** page writes changed values to SQLite, audit-logs the old/new values, and reevaluates all stored orders. Employee workspaces cannot change rules.

## Who can act on a rule-generated task

The Manager workspace may reassign a task, alter its priority or deadline, and update its status. An employee sees only tasks currently assigned to that employee and may update only task status and notes. Marking a task Resolved requires a short resolution note. Each changed operational field receives a clear audit record.
