# Data Model

Schema reference for the Slowbooks PostgreSQL database. 94 tables on
a double-entry accounting foundation. For migration history, see the
files under `migrations/versions/`; for model code, see `app/models/`.

`tests/test_data_model_doc.py` asserts this table list matches
`Base.metadata` exactly — a new model without a row here fails CI.

| Table | Purpose |
|-------|---------|
| `accounts` | Chart of Accounts — asset, liability, equity, income, expense, COGS |
| `customers` | Customer contacts with billing/shipping addresses |
| `vendors` | Vendor contacts |
| `items` | Product/service/material/labor items with rates |
| `invoices` | Invoice headers with status tracking |
| `invoice_lines` | Invoice line items |
| `estimates` | Estimate headers |
| `estimate_lines` | Estimate line items |
| `payments` | Payment records |
| `payment_allocations` | Maps payments to invoices (many-to-many) |
| `transactions` | Journal entry headers |
| `transaction_lines` | Journal entry splits (debit OR credit) |
| `bank_accounts` | Bank accounts linked to COA |
| `bank_transactions` | Bank register entries (with OFX import fields) |
| `reconciliations` | Bank reconciliation sessions |
| `settings` | Company settings key-value store |
| `audit_log` | Automatic change tracking for all entities |
| `purchase_orders` | Purchase order headers |
| `purchase_order_lines` | PO line items with received quantities |
| `bills` | Vendor bills (AP mirror of invoices) |
| `bill_lines` | Bill line items with expense account tracking |
| `bill_payments` | Bill payment records |
| `bill_payment_allocations` | Maps bill payments to bills |
| `credit_memos` | Customer credit memos |
| `credit_memo_lines` | Credit memo line items |
| `credit_applications` | Maps credit memos to invoices |
| `recurring_invoices` | Recurring invoice templates |
| `recurring_invoice_lines` | Recurring invoice line items |
| `email_log` | Email delivery history |
| `tax_category_mappings` | Account-to-tax-line mappings for Schedule C |
| `backups` | Backup file records |
| `companies` | Multi-company database list |
| `employees` | Employee records for payroll |
| `pay_runs` | Pay run headers with totals |
| `pay_stubs` | Individual pay stubs with withholding breakdowns |
| `qbo_mappings` | QBO ID ↔ Slowbooks ID mapping for sync deduplication |
| `attachments` | File attachments linked to invoices, bills, etc. |
| `bank_rules` | Pattern-matching rules for auto-categorizing bank imports |
| `budgets` | Budget amounts by account and period |
| `email_templates` | Customizable email templates |
| `inventory_movements` | Per-item qty/cost ledger (purchases, sales, adjustments) |
| `saved_reports` | Named (report_type + parameters) tuples |
| `document_audits` | Per-document SHA-256 ledger for generated documents (W-2/W-3/940/941/SUI/COBRA/e-signature). A linked hash chain — each row commits to its predecessor, so a deletion or edit breaks verification |
| `audit_checkpoints` | Signed chain-tip snapshots of `document_audits`, exportable off-box for independent verification |
| `signature_envelopes` | E-signature envelopes — frozen document body + SHA-256, sealed into the audit chain on signing |
| `portal_accesses` | Audit log for self-service portal hits (success + failure) |
| `login_attempts` | Authentication-attempt audit log |
| `reseller_permits` | Per-entity sales-tax reseller permits with expiration + verification trail |

## Payroll & HR

| Table | Purpose |
|-------|---------|
| `onboarding_tasks` | Per-employee onboarding checklist items with completion tracking |
| `time_entries` | Hours worked, approval state, and the pay run that consumed them |
| `pto_policies` | Accrual policies — rate, method, carryover cap, max balance |
| `pto_accruals` | Per-employee balance, accrued YTD, and used YTD against a policy |
| `pto_requests` | Time-off requests with approve/reject lifecycle |
| `benefit_codes` | Deduction/contribution catalog (401k, HSA, health) with pre/post-tax treatment and GL routing |
| `benefit_rates` | Dated rate rows per benefit code — the rate in force on a period end date |
| `employee_groups` | Named groups used to attach a common set of benefit codes |
| `employee_group_benefits` | Which benefit codes a group confers |
| `employee_benefits` | Per-employee enrollments in a benefit code, with rate/cap overrides |
| `benefit_ytd` | Year-to-date accumulators per employee and benefit code |
| `pay_stub_benefits` | Per-stub benefit amounts, employee and employer side |
| `garnishment_orders` | Court-ordered garnishments — type, calc method, priority, agency |
| `garnishment_remittances` | Money withheld and owed to an agency, with mark-remitted trail |
| `pay_schedules` | Named pay cadences — frequency, anchor date, lead days, weekend shift |
| `work_locations` | Places of work with validated state/locality tax jurisdictions |
| `employee_bank_accounts` | Direct-deposit destinations (encrypted at rest) |
| `contractor_pay_runs` | Batch 1099 contractor pay runs with JE + NACHA export |
| `contractor_payments` | Per-vendor payment lines inside a contractor run |
| `vendor_bank_accounts` | Contractor ACH destinations for NACHA generation |
| `benefit_plans` | Benefit plan catalog — carrier, type, coverage tiers, costs |
| `benefit_enrollments` | Per-employee elections (ePHI — encrypted, blind-indexed) |
| `benefit_dependents` | Dependents covered under an enrollment (ePHI — encrypted) |
| `wc_class_rates` | Workers' comp carrier class rates per $100 of payroll |
| `users` | Server Edition user principals — login, role, password hash |
| `api_tokens` | Bearer tokens for machine access, with role and last-used stamp |
| `performance_reviews` | Review lifecycle — draft, submitted, acknowledged |

## Job Costing

| Table | Purpose |
|-------|---------|
| `jobs` | Jobs/projects an invoice, bill or time entry can be attributed to |
| `cost_codes` | Cost-code catalog for breaking a job into billable buckets |
| `cost_types` | Labor/material/equipment/subcontract classification for a cost line |
| `job_budgets` | Budgeted amounts per job and cost code |
| `job_costs` | Posted cost documents against a job |
| `job_cost_lines` | Line detail for a job cost document |
| `equipment` | Equipment units whose hours are charged to jobs |

## Classes & Preferences

| Table | Purpose |
|-------|---------|
| `classes` | Class dimension for departmental/segment reporting (Program in nonprofit mode) |
| `user_preferences` | Per-user UI preferences |
| `ocr_templates` | Saved OCR field regions per vendor document layout |

## Fixed Assets

| Table | Purpose |
|-------|---------|
| `fixed_asset_types` | Asset categories with default useful life and depreciation method |
| `fixed_assets` | Capitalized assets with cost, in-service date and accumulated depreciation |

## Nonprofit

| Table | Purpose |
|-------|---------|
| `in_kind_gifts` | Donated goods and services received |
| `in_kind_gift_lines` | Line detail and fair-value basis for an in-kind gift |
| `allocation_rules` | Rules that spread shared costs across functional categories |
| `allocation_rule_targets` | Per-rule destination weights |
| `functional_allocations` | Posted functional-expense allocation runs |
| `functional_allocation_lines` | Line detail for an allocation run |
| `restriction_releases` | Movement of funds from donor-restricted to unrestricted |
