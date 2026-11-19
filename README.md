# Care Collective Operations

A runnable Python/SQLite portfolio prototype covering **four operational areas**: resident records, charges/payments, inventory, and operational tasks. Python **3.11+**, standard library only.

Created in November 2026 as a new implementation inspired by the requirements project in my resume. This is not a historical client deployment. The included seed records are fictional.

## Start

~~~bash
git clone https://github.com/abelberhanuu/care-collective-operations.git
cd care-collective-operations
python app.py --demo
~~~

Open **http://127.0.0.1:8766**. Use a new database for an unseeded workspace:

~~~bash
python app.py --database data/empty.db
~~~

To reopen the seeded workspace, omit --demo. Seeding refuses a nonempty database, and no reset/delete action is provided.

## Functional workflows

| Area | Implemented behavior |
| --- | --- |
| Residents | Create residents, unique units, archive/reactivate while retaining financial history |
| Charges/payments | Append ledger entries, exact integer cents, foreign-key validation, per-resident balances |
| Inventory | Add items, unique SKUs, transactional adjustments, negative-stock prevention, reorder flags |
| Operations | Add tasks, change open/doing/done status, flag overdue tasks |
| Reporting | Summary cards, balance CSV, latest 100 ledger entries and 30 audit events |

Changes and audit records are committed together. Money is accepted as a decimal string with at most two places; the database stores integer cents. Payment amounts may exceed charges and produce a credit balance. Outstanding totals sum positive resident balances, including archived records with debt.

## Demo walkthrough

1. Observe two fictional residents and an opening outstanding total of **$1,300**.
2. Record a $200 payment for Avery Demo; that resident's balance becomes $0.
3. Add stock to the paper towels item and see its reorder flag clear.
4. Mark the sample task done and see the open-task count fall.
5. Download the balance CSV and inspect the audit log.

These values demonstrate fixture behavior, not organizational or business results.

## HTTP interface

Read endpoints: GET /api/state and GET /api/balances.csv.

Write endpoints:
- POST /api/residents
- POST /api/residents/{id}/status
- POST /api/ledger
- POST /api/inventory
- POST /api/inventory/{id}/adjust
- POST /api/tasks
- POST /api/tasks/{id}/status

Writes require application/json and an X-Local-Token obtained from GET /api/session. The browser handles this automatically. Cross-origin writes and unexpected Host headers are rejected. This guard is not user authentication.

## Verify

~~~bash
python -m unittest discover -s tests -v
~~~

Tests exercise exact money, balances, foreign keys, duplicate units, historical retention after archiving, inventory rollback, task dates/status, CSV formula escaping, persistence, and HTTP session/origin guards. CI covers Python 3.11–3.13.

## Scope

The service binds only to loopback. It is a single-user demonstration without accounts, roles, encryption-at-rest, production backups, or healthcare compliance controls. Use synthetic records only. Do not expose it to a network or enter real resident/financial information.

The audit trail is an application change log, not a tamper-evident compliance system. No throughput, user adoption, cost savings, or deployment reliability is claimed.

Source: operations.py (schema/business rules), app.py (routes/CLI), web.py (local HTTP), static/ (dashboard), tests/ (verification).
