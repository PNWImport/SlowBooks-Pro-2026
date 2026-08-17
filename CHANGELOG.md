# Changelog

Notable changes between releases. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/). The internal build order
used during development is captured here so the README can stay focused
on what the software does, not on what sprint shipped what.

## [Unreleased]

### Work locations — first-class tax jurisdictions

Tax situs previously lived in two free-typed per-employee columns;
opening a second office meant editing every employee. `WorkLocation`
pins address + state + locality + default workers'-comp class once,
validated against the state-engine registry and the locality files at
create/update time (a typo'd jurisdiction is a 400, not a silent $0).
Employees attach via `location_id`; payroll resolves jurisdiction most
specific first — per-stub override, explicit employee columns, then the
location. `/api/locations`: CRUD, assign, roster. Migration
a7b8c9d0e1f3. 6 new tests (642 -> 648).

### Tipped wages — tip credit, top-up guarantee, Form 8846

`PayStubInput.reported_tips` (received directly — taxed through the
check but not paid on it) and `paycheck_tips` (paid through payroll).
Both join taxable and FICA wages; hourly tipped stubs get the FLSA
top-up automatically when cash wages + tips miss the MINIMUM_WAGE floor
(config, federal $7.25 default alongside TIPPED_MINIMUM_WAGE $2.13).
Net pay backs reported tips out — the check funds the tax on them, which
is why a low-cash-wage server's check can be nearly zero. The payroll JE
excludes reported tips from wage expense (customers paid them, no cash
leaves the bank) so the entry balances. Form 8846 FICA tip credit at
`GET /api/tax-forms/fica-tip-credit?year=` — employer 7.65% on tips
above the statutory $5.15/h pin, per employee. Form 8027 (allocated
tips) needs gross-receipts tracking and stays a follow-up. Migration
f6a7b8c9d0e2. 10 new tests (632 -> 642).

### Garnishment remittance — the withheld money now owes someone a payment

Garnishments were calculated and withheld, then the money vanished into
"Other payroll deductions payable" with no record of who it was owed to
— the classic small-employer garnishment failure. Now: orders carry the
agency payee (agency_name/address, remit_reference); every processed
pay run writes a `garnishment_remittances` row per order (parsed from
the stub's per-order detail, so the amount is exactly what was
withheld, CCPA-limited percent orders included); the register at
`GET /api/deductions/garnishments/remittances` shows pending totals and
nags rows whose order has no agency on file; mark-remitted records the
outgoing payment reference and is double-remit-proof. Draft runs create
nothing. e-IWO / NACHA CCD+ child-support addenda remain follow-ups.
Migration e5f6a7b8c9d1. 8 new tests (624 -> 632).

### Termination workflow — final-paycheck deadlines + PTO payout

`POST /api/employees/{id}/terminate` answers the two questions every
offboarding asks. (1) When is the final check due? Per-state rules keyed
by voluntary/involuntary (CA: immediately when fired, 72 hours on a
quit; ~16 states with specific shapes; everything else defaults to next
regular payday, resolved to a real date when the employee has a pay
schedule attached). (2) Must accrued vacation be paid out? States that
treat it as earned wages force the payout; elsewhere it defaults on and
the operator can decline. The payout prices accrued balances at the
hourly-equivalent rate (salary / 2080), sick time only on opt-in, and
stages as a DRAFT off-cycle supplemental run like retro pay. Side
effects: is_active off, recurring deductions deactivated, portal token
revoked. The final *regular* paycheck is deliberately not automated —
its hours depend on the timecard; the endpoint reports the statutory
deadline instead. Rules are approximate and say so (final-paycheck
statutes carry penalties — verify with the state labor department).
Migration d4e5f6a7b8c0. 10 new tests (614 -> 624).

### Retro pay + mid-period rate proration

Two halves of "the rate changed":

- Mid-period raise: `PayStubInput.rate_change_date` + `old_rate`
  day-weight a salaried period across both rates ($52k→$78k biweekly
  with the raise at day 8 of 14 pays $2,500).
- Retro pay: `POST /api/payroll/retro-pay/preview` compares every
  non-void regular stub since the effective date against the new rate —
  hourly stubs re-price their recorded regular/1.5x/2x hour split,
  salary stubs use the per-period difference, bonus/off-cycle runs are
  excluded (a bonus isn't underpaid by a raise). `/apply` raises the
  employee's rate and stages the shortfall as a DRAFT off-cycle run
  with supplemental (flat 22%) withholding, ready for review and
  processing. Negative retro (a rate cut) is rejected — clawing back
  paid wages is a legal question, not a payroll calculation.

10 new tests (604 -> 614).

### Pay schedules — named pay calendars

A bare PayFrequency enum says "biweekly" but not which Fridays, when the
submission cutoff falls, or what happens on a weekend pay date. New
`PaySchedule` (frequency + anchor pay date + submission_lead_days +
weekend_shift) pins all three. `/api/pay-schedules`: CRUD, an
`/upcoming` preview (derived dates, shifted flags, per-date cutoffs),
and `/assign/{emp_id}` which attaches the employee and keeps
pay_frequency synced so withholding annualization follows the schedule.
Date math: weekly/biweekly step from the anchor; semi-monthly pays the
anchor day + that day ±15 capped to month end (Feb 30th → 28th);
monthly caps the 31st; shifting applies last so it never changes which
period a date belongs to. Migration c3d4e5f6a7b8. Holiday calendars and
blackout dates are follow-ups (weekend-only shifting today). 9 new
tests (595 -> 604).

### Contractor pay runs — 1099 payees get the payroll shape

Contractors previously lived only in AP (create bill, pay bill). Paying a
roster every period wants the payroll shape — one dated run, many payees,
one JE, one NACHA file — with no withholding: 1099 payees get gross.

- `POST /api/contractor-runs` (batch create) → `/{id}/process` (DR 6130
  contractor expense falling back to 6000, CR 1000 bank; closing-date
  guard; idempotent) → `/{id}/nacha` (ACH credits per contractor from the
  shared NACHA record builders; unbanked vendors skipped — paid by check)
- `VendorBankAccount` — Fernet-encrypted routing/account, clear last-4,
  one active account per vendor (adding supersedes), 9-digit routing
  validation. `POST/GET /api/contractor-runs/vendors/{id}/bank`
- 1099-NEC totals now sum BOTH payment paths: AP bill payments plus
  processed contractor-run payments (draft runs excluded), so a vendor
  paid $400 through AP and $300 through a run reports $700
- Migration b2c3d4e5f6a7; models registered for create_all/migrations

12 new tests (583 -> 595). API-first: SPA page tracked in docs/todo.md.

### Deposit-schedule determination + payroll tax liability calendar

The honest, local-only version of "we handle your taxes": say exactly
what is due, to whom, and when — without claiming to pay it.

- `GET /api/tax-forms/deposit-schedule?year=` — IRS Pub 15 lookback
  (Jul 1 Y-2 .. Jun 30 Y-1, per-quarter detail): <=$50k → monthly
  depositor, over → semiweekly; new employers default monthly.
- `GET /api/tax-forms/liability-calendar?year=` — date-sorted merge of:
  941 deposits under the determined schedule (monthly due-the-15th
  rolled off weekends; semiweekly Wed-Fri→Wednesday / Sat-Tue→Friday),
  the $100k next-day rule (event + becomes-semiweekly warning),
  de-minimis quarters under $2,500 flagged as payable-with-return, FUTA
  quarterly deposits with the $500 floor and carryover (Q4 remainder
  rides Form 940), quarterly 941 / annual 940 filing dates, and state
  quarterly amounts (state deposit *frequencies* vary too much to model
  — the rows say to check).

Federal holidays are not modelled — weekend-only roll, so a holiday due
date is at most a day early, never late. 20 new tests (563 -> 583).

### Electronic filing exports — EFW2 (SSA) + Pub 1220 (IRS 1099)

Year-end forms existed as PDFs only; the electronic upload formats now
generate in-repo (no transport — the operator uploads the files
themselves):

- `POST /api/payroll/forms/efw2/{year}` — SSA Pub 42-007 EFW2 file,
  fixed-width 512-char RA/RE/RW/RT/RF records, unsigned zero-filled
  cents, CRLF. Because the app deliberately stores only SSN last-4,
  every RW ships a zero-filled SSN and a per-employee warning naming who
  needs it filled before upload. Missing EIN is a clean 400.
- `GET /api/tax-forms/1099/fire?year=` — IRS Pub 1220 1099-NEC file,
  750-char T/A/B/C/F records with Payment Amount 1 (NEC) and control
  totals. Vendors over the threshold without a 9-digit TIN are skipped
  *and named* in warnings; a missing Transmitter Control Code is warned.
- Both wired into the Tax Forms page (blob download; warnings surfaced
  as a toast + console detail).
- Fixed a pre-existing wiring bug found on the way: `compute_1099_data`
  filtered on `Vendor.is_1099_eligible`, a column no schema or route
  ever exposed — API-created vendors could never appear on the 1099
  report. It now honors `is_1099_vendor` (the field the API/UI actually
  sets) as well, and `w9_on_file` is settable through the vendor API.

Layouts are best-effort transcriptions of the specs — run EFW2 output
through SSA AccuWage and verify both against the current-year pubs
before uploading. 12 new tests (551 -> 563).

### Quarterly SUI wage report — endpoints for the existing aggregation

`compute_sui` shipped as scaffolding with the tier-3 tax forms but had no
endpoint. Now: `POST /api/payroll/forms/sui/{year}/{quarter}` (JSON, the
machine-readable contract) and `.../pdf` (WeasyPrint, audit-hashed via
`document_audits` like every other tax form), both taking an optional
`?state=XX` filter for multi-state employers. The PDF is the generic
per-employee wage-detail layout every state's quarterly UI return is built
from (employee, SSN last-4, total wages, SUI-taxable wages, SUI tax) — a
transcription source for the state's own form or upload portal, not a
pixel replica, and it says so on the page. 15 new tests (536 -> 551).

### Local / municipal payroll tax layer

The tax layer below the states: PA EIT + LST, OH municipal + school
district, NYC/Yonkers, MD and IN county taxes, KY occupational license
fees, MI city income taxes. Same table-driven design as the state work —
one engine (`app/services/local_tax/engine.py`), reviewable JSON under
`localities/` with per-file provenance and a `verified` flag (all shipping
unverified), validation at load.

Rules declare a `basis` — `work` (OH municipal, KY, Philadelphia),
`residence` (MD/IN counties, OH school districts, NYC), `higher_of`
(PA Act 32), `work_or_residence` (MI cities with the residence-city
credit) — and an amount kind: `percent`, `brackets` (NYC progressive),
or `percent_of_state_tax` (Yonkers resident surcharge; its nonresident
wage tax rides the same rule). PA LST flat annual amounts prorate into
level per-period installments. Residency is never assumed: an unset
residence_locality withholds at the nonresident rate, and unknown codes
are surfaced in `unknown_localities` rather than silently taxing $0.

Plumbing: `Employee.work_locality` / `residence_locality` (+ per-stub
override), `PayStub.local_tax` / `local_tax_employer` / `work_locality`
(migration a1b2c3d4e5f6), W-2 boxes 18-20, payroll JE "Local tax payable"
line, disposable-earnings interaction with garnishments, YTD `local`
total, gross-up awareness. 36 new tests (500 -> 536). Simplifications
(MI credit, Act 32 pairing, no LST exemption) documented in
docs/local-taxes.md.

### 50-state payroll withholding — table-driven state engines

Payroll worked in four states. WA, CA, NY and OR had hand-written engines;
every other state resolved to `GenericStateEngine(flat_rate=0)` and withheld
**no state income tax at all**. An employee in Illinois got a paycheck with a
blank state line. That was a deliberate, honest fallback — a wrong guess is
worse than nothing — but it capped the product at four states.

**What was added:**

- `app/services/state_tax/table_engine.py` — `TableDrivenStateEngine`, one
  implementation of the shape almost every state shares: annualize the
  period's taxable wages, subtract a standard deduction and exemption
  allowance, apply a flat rate or walk a progressive bracket schedule, divide
  back down to the period. State-specific disability / paid-leave premiums
  are applied against their own wage bases. Tables are validated at load —
  a malformed one raises `StateTaxTableError` at startup or in tests, never
  partway through a pay run.

- `app/services/state_tax/tables/*.json` — 47 tables covering every state
  without a dedicated engine, plus DC. Rates, bracket edges, deductions,
  exemptions, SUTA wage bases and premium definitions all live here as
  reviewable data rather than constants buried in Python. Each table carries
  its own provenance: `tax_year`, a `source` URL pointing at the state's
  published withholding guide, and a `verified` flag.

- Dedicated engines still win. WA (per-hour L&I by risk class) and OR
  (transit taxes) have rules the generic shape cannot express, so the
  registry checks `_DEDICATED` before the tables.

**Verification status — every table ships `"verified": false`.** The figures
approximate the published 2026 schedules and are in the right neighbourhood,
but nobody has checked them against the source. Bracket edges, deductions and
wage bases change annually. `python -m app.services.state_tax.table_engine`
prints coverage and verification status so the unchecked states stay visible.
`PAYROLL_STRICT_TAX_TABLES=1` makes an unverified table withhold nothing and
label the omission on the stub, for operators who would rather fail loud than
withhold an unreviewed amount.

**Per-state SUTA.** A single global `SUTA_RATE` was applied in every state,
which is wrong the moment you hire outside your home state — wage bases alone
range from $7,000 (FL, AR) to $72,800 (WA). Rate resolution is now, most
specific first: an explicit per-run rate → `SUTA_RATE_BY_STATE`
(`"WA:0.0121,OR:0.024"`) → `SUTA_RATE` when the stub is in `EMPLOYER_STATE` →
the state's published new-employer rate → `SUTA_RATE`. Step three matters: an
operator who set `SUTA_RATE` meant it for their home state, and a published
new-employer rate must not silently override the real experience rate they
entered. The wage base always follows the work state; reciprocity moves
income tax to the residence state but never unemployment tax.

**Known simplification:** `exemption_allowance` is a per-status annual amount
assuming one allowance. States computing exemptions from allowances claimed
on a state W-4 need an `Employee.state_allowances` column, which does not
exist yet — so those employees are over-withheld slightly. Tracked in
`docs/todo.md`.

- `tests/test_state_tax_tables.py` — 48 tests. Structural coverage (every
  jurisdiction resolves to a real engine, tables validate, malformed input
  rejected) plus hand-derived arithmetic for a flat state (IL), a bracket
  state (VA) and a premium state (NJ), and the full SUTA resolution order.
- `docs/state-tax-tables.md` — schema reference and the verification workflow.

452 → 500 tests.

### AP void — `POST /api/bill-payments/{id}/void`

The customer-payment void (`POST /api/payments/{id}/void`) had no AP mirror.
Any voided customer receipt restored A/R cleanly; vendor bill payments could
not be undone at all. This gap is now closed.

**What was added:**

- `app/routes/bill_payments.py` — `void_bill_payment()` endpoint. Acquires a
  `with_for_update()` row-lock on the payment before checking `is_voided`,
  so two concurrent void requests cannot both pass the guard and post
  duplicate reversing JEs. Posts a reversing JE (swaps debit/credit on every
  original JE line). Walks each `BillPaymentAllocation` with a second
  `with_for_update()` lock and restores `amount_paid` / `balance_due` /
  `status` on each bill. Respects the closing-date guard — cannot post a
  reversing JE into a locked period.

- `app/models/bills.py` — `is_voided = Column(Boolean, …)` on `BillPayment`.

- `app/schemas/bills.py` — `is_voided: bool = False` on `BillPaymentResponse`.

- `migrations/versions/c9d0e1f2a3b4_add_is_voided_to_bill_payments.py` —
  Alembic migration adds the column with `server_default=false()`.

- `app/static/js/bills.js` — `BillsPage.voidBillPayment()` wires the new
  endpoint to the UI so the wiring audit passes.

**Test coverage:**

- `tests/test_void_reversal_symmetry.py::test_bill_payment_void_restores_bill_balance`
  — full void cycle: bill paid → void → balance restored, ledger balanced,
  double-void rejects 400.
- `tests/test_closing_date_enforcement.py::test_bill_payment_void_respects_closing_date`
  — reversing JE cannot land in a closed period.

---

### Whole-repo lint & format sweep

`black 24.8` and `ruff 0.6` run against `app/ tests/ scripts/` without an
allowlist — every file is now clean. CI replaced a 30-line per-file allowlist
with a two-line whole-tree gate.

Fixes applied to reach a clean tree:

- **E402** (imports not at top of file) in `app/routes/invoices.py`,
  `app/routes/stripe_payments.py`, `app/routes/reports.py`,
  `app/routes/saved_reports.py`, `app/services/iif_import.py`.
- **E741** (ambiguous `l` variable name) in `app/services/accounting.py`,
  `app/routes/journal.py`, `app/routes/reports.py`,
  `app/services/iif_import.py`, `app/services/tax_export.py`,
  `scripts/repair_rounding_drift.py`.
- **black reformatting** of ~40 files with over-long lines.

---

### Books-balance invariant tests (`test_books_balance_invariants.py`)

Seven cross-feature invariant tests that exercise the entire accounting layer
end-to-end through the API:

1. Every posted JE has `Σ debit == Σ credit`.
2. Full ledger `Σ debit == Σ credit` across all transactions.
3. Balance sheet balances: `A == L + E` (with synthetic Net Income line).
4. A/R aging total matches open invoice balances.
5. A/P aging total matches open bill balances.
6. Analytics A/R widget matches `/api/reports/ar-aging`.
7. P&L net income matches the balance-sheet synthetic equity line.

`_build_scenario()` creates a realistic dataset (3 invoices, 2 bills,
payments at various states) before each invariant check.

---

### Shell-injection AST audit (`test_subprocess_safety_audit.py`)

Four CI-gated static-analysis tests that verify the subprocess/shell call
surface is safe:

1. Zero `subprocess.*` calls in `app/` or `scripts/` use `shell=True`.
2. Zero `os.system` / `os.popen` / `commands.getoutput` in production code.
3. All three subprocess callsites use list-form args (not string
   interpolation).
4. Every bash script in `scripts/` double-quotes all `$VAR` expansions.

Uses `ast.NodeVisitor` for Python files; regex for shell scripts. Runs in
< 1 s. Result: zero vulnerabilities found in the codebase.

---

### Void-reversal symmetry tests (`test_void_reversal_symmetry.py`)

Six property-based invariant tests for void semantics:

1. Full payment void restores invoice balance and keeps ledger balanced.
2. Partial payment void restores only the voided portion.
3. Bill-payment void restores bill balance, keeps ledger balanced, double-void
   rejects 400.
4. Invoice void (no payments applied) → status VOID, balance\_due 0, ledger
   balanced.
5. Invoice void with payments applied rejects 400/409 (would double-reverse
   A/R).
6. Double-void of same payment rejects or is a no-op — never posts a second
   reversing JE.

---

### Closing-date exhaustive sweep (extended `test_closing_date_enforcement.py`)

Expanded from 3 to 13 tests. Added `test_bill_payment_void_respects_closing_date`
(the AP void guard), plus nine exhaustive sweep tests covering every
direct-create route that accepts a user-supplied date and posts a JE:
invoices, bills, payments, bill-payments, credit memos, journal entries,
CC charges, deposits, batch payments.

---

### IIF round-trip tests (`test_iif_round_trip.py`)

Three tests verifying the Intuit Interchange Format export/import pipeline:

1. Chart-of-accounts export → reimport preserves all accounts by number.
2. Customer names with metacharacters (`\t`, `\n`) are sanitized on export;
   the sanitized record can be reimported cleanly.
3. Invoice TRNS + SPL rows sum to zero (double-entry identity): the A/R debit
   plus income credits plus tax credit == 0.

---

### Production-readiness sweep (rounding / races / N+1 / closing-date / secrets)

A 19-commit program-wide audit of every JE-posting path and money
boundary in the codebase. All 452 tests pass; live walkthrough
exercised every flow listed below.

**Money math — rounding drift fixed at the source.**
The class of bugs: `qty * rate` was stored to `Numeric(12, 2)` columns
without being quantized first. SQL rounded each line on the way in,
so `sum(line.amount)` no longer equaled the stored `subtotal` after a
round-trip. Fix: every per-line money expression now goes through
`_q()` (ROUND_HALF_UP at 2 decimals) **before** being assigned. Applied
to invoices, bills, POs, estimates, credit memos, and the recurring
invoice generator. `compute_line_totals()` is the single canonical
helper. `scripts/repair_rounding_drift.py` detects and repairs
pre-fix rows (dry-run by default; `--apply` writes).

**Auto-number races — IntegrityError retry on every doc series.**
`SELECT MAX(num) + 1` followed by `INSERT` has no lock. Two concurrent
creates would both see the same MAX and collide on the UNIQUE
constraint. `create_invoice`, `create_po`, and `create_estimate` now
catch `IntegrityError`, roll back, and retry up to 10 times. Pinned
by `tests/test_invoice_number_race.py`.

**N+1 SELECT storm — eager-loaded every list endpoint.**
`for inv in invoices: inv.customer.name` was firing one SELECT per
row. Added `joinedload(.customer)` + `selectinload(.lines)` to
invoices, bills, POs, estimates, payments. Also clamped `skip`/`limit`
on every list route (1 ≤ limit ≤ 1000; skip ≥ 0). Pinned by
`tests/test_no_nplus1_in_list_endpoints.py`.

**Closing-date enforcement — plugged three bypass paths.**
A code audit found three routes that posted dated JEs without calling
`check_closing_date`:
- `POST /api/purchase-orders/{id}/convert-to-bill`
- `POST /api/estimates/{id}/convert`
- `POST /api/payroll/{id}/process`

Each one let an operator land a JE into a closed period by routing
through a "convert" or "process" verb instead of the direct create.
All three now call the guard. Pinned by
`tests/test_closing_date_enforcement.py`.

**Stripe webhook idempotency under contention.**
Stripe retries with backoff; two webhook deliveries can land
milliseconds apart. The check-then-insert against `Payment.reference`
let both pass the existence guard and create duplicate payments. Fix:
`with_for_update()` on the invoice row before the idempotency check,
so the second arrival serializes behind the first and sees the
already-recorded payment.

**Settings — secret redaction on GET.**
`GET /api/settings` was returning `stripe_secret_key`,
`smtp_password`, `closing_date_password`, and the QBO tokens in
plaintext. Fix: response runs through `_redact_secrets()`, which
replaces any non-empty secret with `"********"`. `PUT` treats the
placeholder as a no-op so a UI round-trip can't overwrite the real
value with `"********"`. Pinned by `tests/test_settings_redaction.py`.

**Input validation at the boundary.**
Schema-level rejection of impossible inputs: zero-line invoices /
bills / POs / estimates (422), negative quantity / rate / hours (422),
zero or negative payment amounts (400), payment allocations exceeding
invoice balance (400), duplicate `(vendor_id, bill_number)` pairs
(409). 17 tests in `tests/test_input_validation.py`.

**Payment void race.**
`void_payment` walked allocations and decremented `invoice.balance_due`
without locking. Concurrent voids could double-credit. Fix:
`with_for_update()` on both the payment and each invoice in the
allocation loop.

**Reconciliation drift.**
`sum(float(t.amount) ...)` over hundreds of cleared transactions
produced sub-cent float drift that made a truly-zero difference
display as `$0.00000001`. Replaced with `Decimal(str(...))`
arithmetic; convert to float only at the JSON boundary.

**Analytics AR aging consistency.**
The dashboard widget bucketed by **days-since-invoiced**; the
`/api/reports/ar-aging` endpoint bucketed by **days-past-due**. Same
data, different bucket → operator confusion. Analytics now matches
the report.

**Balance sheet — synthetic Net Income equity line.**
With no equity accounts holding transactions, the balance sheet
showed `Total Equity = 0` even though the books balanced. Now
computes net income from income/COGS/expense accounts and appends a
synthetic "Net Income (current period)" line to equity. A − L − E = 0.

**AR aging filter — include DRAFT.**
Aging was filtering `[SENT, PARTIAL]` only, hiding draft invoices with
open balances. Now `[DRAFT, SENT, PARTIAL]` at all 10 filter sites.

**Schema response types — Decimal not float.**
`BillResponse`, `BillLineResponse`, `POResponse`, `CreditMemoResponse`
were serializing money as `float`. Now `Decimal`. Round-trip stays
exact through the wire.

**Error handling — 4xx / 5xx mapping.**
`get_1099_pdf` was 500ing on a `ValueError` (not-found case); now
404. `restore_backup` always returned 500 regardless of cause; now
maps to 400 / 404 / 500. `low_stock_items` now surfaces oversold
inventory (`qty < 0`) regardless of reorder_point.

**IIF export — tab/newline sanitization.**
A vendor name with a `\t` in it would split that field into two on
import elsewhere. `_iif_clean()` now strips `\t\r\n` from every
field value before emission.

**Payroll input validation.**
`PayStubInput` schema rejects negative hours / overtime / deductions
/ gross_override at the boundary.

**IIF import — quantize SPL amounts.**
`_import_invoice` and `_import_estimate` now `_q(abs(...))` each SPL
amount before accumulating, matching the rounding semantics of
native invoice creation.

**Decompressed inventory restore audit, SSRF hardening, proxy
correctness** (batch 3 of the earlier enterprise eval) — see commits
`749b96e`, `f0c5816`, `87c0222`.

### Red-team pass on WC3D's Jinja2 XSS fix
WC3D's commit `ca6182f` enabled `autoescape=True` on the two Jinja2
Environments he found (`app/routes/public.py`,
`app/services/pdf_service.py`). A red-team sweep of every other
Jinja2 construction in `app/` turned up **one more spot** missing
the same fix:

- `app/services/email_service.py:139` — `SandboxedEnvironment()`
  (used to render admin-editable email templates with customer-
  supplied data injected as context). Fixed:
  `SandboxedEnvironment(autoescape=True)`.

- Same file, line 156–164 — when the file-based template fails, the
  fallback path was f-string-interpolating `invoice.customer.name`
  directly into an HTML body. Routed through `html.escape()` now.

Added `tests/test_jinja_autoescape_audit.py` — walks every
`Environment(...)` / `SandboxedEnvironment(...)` call in `app/`
(with a proper balanced-paren walker, since `Environment(loader=
FileSystemLoader(...))` defeats a naive `[^)]*` regex) and fails CI
if any one is missing `autoescape=`. The rule can't drift back.

Also verified the JS side: `toast()` uses `textContent`, so all
`toast(\`...${user.name}...\`)` calls are safe by construction;
`openModal()` uses `textContent` for the title (safe) and
`innerHTML` for the body (relies on per-call `escapeHtml()`, which
36 of 40 JS files use — the remainder don't render user-strings).
The broader JS-innerHTML-XSS class is a separate concern already
tracked under the CSP-unsafe-inline-cleanup item in `docs/todo.md`.

### Layout: `alembic/` → `migrations/`
Database migration scripts moved from `alembic/` to the more
conventional `migrations/` at the top level. `script_location` in
`alembic.ini` updated; references in CONTRIBUTING, PR template, and
docs all retargeted. The `alembic` CLI command itself is unchanged
(reads alembic.ini for its script_location), so `alembic upgrade
head` in `docker-entrypoint.sh` keeps working. Git tracked the moves
as renames, so blame history is preserved.

### Schema-wide date-collision fix (the rest of jake-378's pattern)
jake-378 previously fixed the `date: date` field-name-shadows-type
collision in `app/schemas/invoices.py` and `estimates.py` (commits
48cdb79, e12bbb1). A quick reproducer confirmed **pydantic 2.13 still
has the same bug**:

```python
class Update(BaseModel):
    date: Optional[date] = None   # Optional[<the field>] not Optional[date]
                                   # -> "Input should be None" on every value
```

Same pattern existed in **9 more schemas** (banking, bills, cc_charges,
credit_memos, deposits, journal, payments, purchase_orders,
time_entries) — applied jake's `from datetime import date as dt_date`
rename uniformly across all of them. Added
`tests/test_schemas_audit.py` to lock in the rule so the bug can't
drift back in via a new schema file. (296 tests now passing, up from
295.)

### PostgreSQL version doc alignment
Compose files (both dev and prod) already ship `postgres:17-alpine`,
but `README.md`, `INSTALL.md`, `docs/development.md`, and
`docs/operations.md` all said "PostgreSQL 16" or `brew install
postgresql@16`. Same lag-vs-reality pattern as the Python version
fix. Docs now match what's actually deployed (17).

### Dependency upgrade pass
Five hard-pinned (`==`) deps in `requirements.txt` were months behind.
Pins relaxed to floor-and-cap ranges so future patch/minor bumps land
without needing a release. All upgrades are stable 2.x → 2.x or
patch-only; no API churn expected. pip-audit on the new requirements
remains clean (zero known CVEs).

| Dep | Was | Now | Installed (verified) |
|---|---|---|---|
| `alembic` | `==1.13.3` | `>=1.16.0,<2.0` | 1.18.4 |
| `sqlalchemy` | `==2.0.35` | `>=2.0.40,<3.0` | 2.0.49 |
| `pydantic` | `==2.9.2` | `>=2.11.0,<3.0` | 2.13.4 |
| `pydantic-settings` | `==2.5.2` | `>=2.10.0,<3.0` | 2.14.1 |
| `uvicorn[standard]` | `==0.30.6` | `>=0.32.0,<1.0` | 0.47.0 |

Tests: 295 passing on the upgraded set (no source changes needed).

### Python version doc alignment
`README.md`, `INSTALL.md`, and `docs/development.md` all said "Python
3.12" or "3.12+", but the Dockerfile, every CI job, and the CVE
comments in `requirements.txt` reference Python 3.13. Docs now say
3.13 (the actual tested version); INSTALL.md notes that 3.12 may work
but isn't gated by CI.

### CRM-side UX additions
- **Customer Details modal** — clicking a customer row now opens a
  single-screen popout (no sub-tabs) with billing/shipping addresses,
  autosaving notes, attached reseller permits, recent invoices, and
  recent payments. Closes the "where do we put notes for everyone to
  see?" gap.
- **Reseller permits module** — new `#/reseller-permits` page with
  expiring-soon strip, per-state format validation (WA 9-digit, CA
  9-12, TX 11), copy-permit/business-name/tax-ID buttons, and a
  unified Verify workflow that opens the state's official lookup site
  in the default browser (`window.open('_blank', 'noopener,noreferrer')`
  after a confirm dialog) then stamps `last_verified_at` / disables
  with an inactive marker. Backend has CRUD + `/expiring` +
  `/validate-format` + `/mark-verified`. Pure record-keeping — there
  is no fake "API call" to the state; the operator does the lookup,
  we record the verification trail.
- **Admin Sign Out button** — topbar now has a dedicated logout button
  that POSTs `/api/auth/logout` and reloads to the splash page. The
  endpoint was live; only the button was missing.

### Test infrastructure
- **Bidirectional wiring audit** — `tests/test_wiring.py` already
  asserted every JS `API.*` call resolves to a route; it now also
  asserts every backend `/api/*` route has a JS caller (or is on the
  `_INTENTIONAL_BACKEND_ONLY` allowlist). The catch-all collector
  picks up template-literal paths (including paths assigned to a
  variable before `API.post(url, …)`), `href=`/`action=` attributes
  in JS-rendered HTML, and `window.open('/api/…')`. Pre-substitutes
  `${…}` blocks before regex matching so nested `encodeURIComponent`
  expressions don't break the path capture. Each allowlist entry now
  carries a comment explaining *why* the route has no SPA caller
  (admin-only, scheduled job, drill-down endpoint shadowed by the
  bundled `/dashboard` response, future UI tab, etc.).
- **Audit hook coverage in tests** — `conftest.py` was creating a
  fresh per-test session factory but never re-attaching the
  `after_flush` audit hook to it, so the entire audit-log mechanism
  was silently bypassed in every existing test. The fixture now calls
  `register_audit_hooks` on the per-test session factory. A new
  matrix test (`test_audit_log_covers_new_entities_but_skips_audit_tables`)
  asserts a ResellerPermit insert lands in `audit_log` and a
  PortalAccess insert does NOT (it's already an audit-flavored table).
- **`_SKIP_TABLES` curated** — `audit_log` was the only entry; added
  `portal_accesses`, `login_attempts`, `document_audits`, and
  `email_log` (every one is itself an audit/log table, and double-
  logging into `audit_log` would just add noise and create a future
  recursion footgun if any of them ever gains a trigger-set `id`).

### Payroll / HR UI additions
- **Portal-token admin view** — Employee Details > Portal Access now
  shows expires-at (red when <30 days), last-used-at, and a
  collapsible recent-access log pulled from `portal_accesses`.
- **PTO accrual editor** — `#/hr/pto` gained an Employee Accruals
  section with enroll-employee-in-policy form and per-row "Run Accrual"
  prompt. Closes the gap where admins had to enroll employees via curl.
- **E-Verify case tracking** — schema additions (`everify_status`,
  `everify_submitted_at`, `everify_closed_at`, `everify_notes`),
  GET/PUT `/api/employees/{id}/everify` endpoints, and a new section
  in the Employee Details modal with color-coded status. Pure
  record-keeping — the federal E-Verify submission still happens via
  the official portal or a vendor; this stores the case so DHS
  inspections find it in one place.

### Partial CSP tightening
- index.html's 11 inline `onclick=`/`oninput=` handlers moved to a new
  `app/static/js/bootstrap.js` that wires them via `addEventListener`
  after DOMContentLoaded. The static shell page now has zero inline
  handlers — would work under a stricter CSP today.
- `'unsafe-inline'` stays in `script-src` and `style-src` because the
  JS-rendered modal templates across the rest of the app still emit
  inline handlers + styles. Removing those is a multi-file refactor
  documented in `docs/todo.md`. Honest accounting added to
  `docs/security-hardening.md`.

### Polish
- `docs/release-checklist.md` section 4 (TLS) now mentions optionally
  submitting the domain to the HSTS preload list once TLS is locked in.

### Audit + ops automation
- **Portal access audit log** — new `portal_accesses` table records
  every authenticated and unauthenticated portal hit (employee_id, IP,
  truncated UA, path, success). Mirrors `LoginAttempt` and gives
  forensic queries something more granular than `portal_token_last_used`.
- **Encryption key rewrap CLI** — `python -m app.services.encryption
  rewrap` re-encrypts every bank-PII blob under the current key, so
  rotation can actually complete (transparent reads via PREV fallback
  was already shipped). Supports `--dry-run`.
- **Wiring audit as a unit test** — `tests/test_wiring.py` grep-and-
  resolves every JS `API.*` call against the registered FastAPI routes.
  Catches typos and stale paths automatically — CI fails when a JS
  caller goes nowhere.
- **End-to-end portal test** — single test walks the entire portal
  lifecycle (mint → claim → 5 cookieless pages → POST PTO → logout →
  cold-401 → force-expire → rotate → claim again).
- **Weekly `pip-audit` GitHub Action** — Sunday cron, opens a
  security-labeled issue on findings (de-duped), fails the workflow run.

### Frontend polish
- **Drag-and-drop document uploads** on Employee Details > Documents.
- **Portal logout button** in `portal/base.html` nav.
- **Branded portal favicon** — `/portal/favicon.ico` serves the
  employer's company logo so each customer's portal carries their own
  bookmark icon.

### Bug fix
- Pay-stub PDF was rendering accountable-plan reimbursements as
  positive line items in the **Deductions** table. Now they have their
  own **Additions to Net (non-taxable)** table above net pay. Net-pay
  math was always right; the display was confusing.

### Tax forms — PDFs, audit hashes, the works
- **WeasyPrint PDF endpoints** — `POST /api/payroll/forms/{w2,w3,940,941}/.../pdf`
  render real printable forms (Acme Co. branded, masked SSN, full box
  data). The existing JSON endpoints stay for future e-file integration.
- **Document audit hashes** — every tax-form PDF carries a SHA-256
  content hash and an audit ID in the footer. Backed by a new
  `document_audits` table with three lookup endpoints
  (`/api/document-audits`, `.../verify/{hash}`, etc.). An auditor with
  the PDF can recompute the hash and confirm authenticity against
  the trust-anchor row.

### Payroll / HR
- **Time-entry → pay-run auto-population** — the pay-run form now has
  a "Use approved time entries" checkbox + live-preview column showing
  unpaid approved hours per employee. Backend was already wired; only
  the frontend opt-in was missing.
- **PTO year-end carryover automation** — new
  `POST /api/pto/accruals/year-end-carryover?target_year=YYYY` endpoint
  caps every accrual at its policy `max_carryover` and resets YTD
  counters, returning a per-row before/after summary.
- **Portal cookie session** — after the first `/portal/{token}` claim,
  the token moves into a `HttpOnly Secure SameSite=Strict` cookie and
  every subsequent URL is cookieless. No more Referer leak, browser
  history, or shared-bookmark exposure. Backward-compat: emailed
  `/portal/{token}` links still work — they just redirect through the
  claim flow once.
- **Portal branding** — every page renders the employer's company name
  and logo in the header (was generic "Employee Portal").
- **State new-hire report PDF branding** — same treatment.

### Authentication / session hardening
- **Login attempt audit log** — new `login_attempts` table records
  every success and failure (IP, UA, timestamp). Catches the slow
  brute-force attacker who paces under the 5/min rate limit.
- **Session rotation on login** — `request.session.clear()` before
  issuing the auth flag, defense-in-depth against session fixation.
- **Idle session timeout** — sliding window via
  `SESSION_IDLE_TIMEOUT_SECONDS` (default 14400s = 4 hours). Sessions
  past the threshold get 401'd and cleared.

### Security
- **App-level `HTTPSRedirectMiddleware`** + HSTS (2-year, includeSubDomains,
  preload) when `FORCE_HTTPS=true`. Session cookie carries `Secure` flag
  in the same conditional.
- **Content-Security-Policy** — `frame-ancestors none`, `object-src
  none`, `form-action self`, Stripe origins allowlisted.
- **Startup fail-hard checks** (production only): refuses to start if
  `PAYROLL_ENCRYPTION_SECRET` is the dev default, `DATABASE_URL` lacks
  `sslmode`, or `FORCE_HTTPS=false`.
- **Portal token expiry** — 1-year hard + 90-day sliding idle. Expired
  tokens return `410 Gone`.
- **Portal headers** — `Referrer-Policy: no-referrer` and
  `Cache-Control: no-store` on every portal response.
- **Encryption key versioning** — bank PII ciphertext now prefixed with
  `v1:`. `PAYROLL_ENCRYPTION_SECRET_PREV` env var supports
  zero-downtime key rotation; decrypt tries current key first, then
  previous.
- **Per-endpoint rate limiting** — portal at 30/min GET / 10/min POST,
  joining the existing 5/min on login.

### Dependency CVE pass
Bumped requirements.txt to close known CVEs surfaced by `pip-audit`:
- `cryptography` — cap raised from `<44.0` to `<47.0`, floor `46.0.5`
  (closes PYSEC-2026-35, CVE-2024-12797, CVE-2026-26007, etc.)
- `fastapi` — bumped from `0.115.0` to `>=0.121.0,<0.122` to allow
  starlette `0.47+`
- New explicit `starlette>=0.47.2,<0.50` pin (closes CVE-2024-47874,
  CVE-2025-54121)
- New explicit `pyjwt>=2.10.0,<3.0` pin (override intuit-oauth's
  transitive 2.7.0 with known CVE)

`pip-audit -r requirements.txt` now reports **zero known
vulnerabilities**.

### Wiring fixes
Spider-web audit of every `API.*` call against every `@router.*`
handler caught four real breakages:
- 3× `API.delete()` typos (`API.del` is the actual export) — `employees.js`,
  `deductions.js`
- Missing `GET /api/pto/policies/{id}` and `PUT /api/pto/policies/{id}` —
  the policy-edit form was 404'ing
- `/approve` and `/reject` alias routes for the PTO `/decision` endpoint —
  the buttons were hitting non-existent paths

### Docs + repo conventions
- **`CONTRIBUTING.md`**, **`.github/PULL_REQUEST_TEMPLATE.md`**,
  **`.github/ISSUE_TEMPLATE/{bug_report,feature_request,config}.{md,yml}`** — the
  standard set this size of repo should have had.
- **`docs/hipaa-compliance.md`** — Security Rule mapping, 8-gap honest
  assessment, deployment recommendations.
- **`docs/security-hardening.md`** + **`docs/wiring-audit.md`** + **`docs/todo.md`** — engineering
  logs for the hardening pass, the wiring audit methodology, and the
  internal TODO scratchpad.
- README de-Phased / de-Tiered — that history now lives in this
  CHANGELOG file instead of cluttering the user-facing readme.

### Cleanup
- **Alembic revision collision fixed** — tier1 was sharing
  `f6a7b8c9d0e1` with the Phase 11 inventory migration. Renamed to
  `f7a8b9c0d1e2`; chain is now linear.
- `test_frontend_pages.py` moved from repo root to
  `scripts/integration_test_frontend.py` (it's a live-HTTP integration
  script, not a unit test).
- `app/templates/invoice_pdf_v2.html` deleted — added 5 weeks ago but
  never wired into `pdf_service.py`.
- `backups/` directory kept tracked (via `.gitkeep`) but contents
  gitignored so dumps don't accidentally land in commits.

### Test coverage
297 tests passing. Up from 119 at the start of this branch's work.
All previously-passing tests still pass.

### Docs reorganization
Root now keeps only `README.md`, `INSTALL.md`, `SECURITY.md`,
`CHANGELOG.md`, `CONTRIBUTING.md` (the conventional set). Everything
else moved into `docs/`.

## [2.0.0] — May 2026

### Added
- **Analytics dashboard** at `#/analytics` — KPI cards plus four charts
  (12-month revenue line, expenses doughnut, A/R+A/P stacked bar,
  90-day cash forecast), MTD/QTD/YTD period selector, CSV/PDF export
  with branded headers.
- **AI Insights** — Optional one-shot executive brief (3 observations /
  3 risks / 3 recommendations) with seven supported providers (xAI Grok,
  Groq, Cloudflare Workers AI, Cloudflare self-hosted gateway, Anthropic
  Claude, OpenAI, Google Gemini). Bring-your-own-key, encrypted at rest.
- **AI Predefined Analyses** — 11 curated actions across 5 categories,
  replacing the earlier free-form chat (more reliable across providers).
- **Inventory ledger** — Perpetual inventory with weighted-average cost,
  automatic COGS journal entries on every sale, reorder points,
  Adjust modal for add/remove/set-to-count.
- **Drill-down reports** — P&L and Balance Sheet rows are click-through
  to source transactions with running balance and source-doc links.
- **Saved Reports** — Name and one-click rerun favorite report configs.
- **Duplicate detection** — Fuzzy matching on customer/vendor names with
  a confirm-and-create-anyway dialog.
- **Setup wizard** collects operator name + email + company name + email
  + password (was password-only).
- **Branded headers** on PDF/CSV exports (SlowBooks Pro 2026 wordmark +
  company logo).

### Changed
- AI provider config moved from a modal to a Settings sub-page with a
  curated model dropdown and Custom escape hatch.
- Items form gained the full inventory toolset (track checkbox, qty,
  reorder point, asset account).
- Customers/Vendors gained the duplicate-warning confirm dialog.

### Security
- **Single-user authentication** — Argon2id-hashed password, session
  cookie (`same_site=strict`, 30-day TTL).
- **Rate limiting** — slowapi at 5 logins/minute per IP.
- **Security headers** — X-Content-Type-Options, X-Frame-Options DENY,
  Referrer-Policy, Permissions-Policy on all responses.
- **CORS lockdown** — explicit origin allowlist, no wildcards.
- **Path traversal protection** — backup and attachment endpoints use
  `Path.is_relative_to()`.
- **Atomic secret writes** — session key uses `mkstemp` + `os.replace()`.
- **Fernet encryption** for AI provider API keys.
- **SSRF protection** — AI provider URLs validated against private IPs
  and metadata endpoints.
- **Constant-time secret compare** in the Cloudflare Worker gateway.
- **Schema-validated AI config payloads.**
- **CSV formula injection protection** — exports neutralize `=`, `+`,
  `-`, `@` cell prefixes.
- **Non-root Docker** — container runs as UID 1000.

### Performance
- Analytics dashboard: 10 SQL queries, ~26 ms engine on 3,000 invoices
  plus 1,500 bills.
- Test suite runs in under 30 seconds with zero network dependencies.

### Fixed
- Dark mode now works on every report subtotal row (missing `--gray-50`
  definition).
- `--text-main` typo fixed.

## Earlier releases

Internal build history before v2.0.0 lived under "Phases" 1-11. A
recap of what each phase covered:

| Phase | Scope |
|-------|-------|
| 1 | Foundation — audit log, full-text search |
| 2 | Accounts Payable — POs, bills, bill payments, credit memos |
| 3 | Productivity — recurring invoices, batch payments |
| 4 | Communication & Export — CSV import/export, uploads |
| 5 | Advanced integration — bank import (OFX/CSV), tax export, backups |
| 6 | Companies, employees, payroll |
| 7 | Online payments (Stripe) |
| 8 | QuickBooks Online sync |
| 9 | Analytics + journal entries + deposits + credit-card charges + checks |
| 9.5 | AI Insights layer |
| 9.7 | Single-user authentication, rate limiting, security audit pass |
| 10 | Bank rules, budgets, attachments, email templates |
| 11 | Inventory ledger, drill-down reports, fuzzy duplicate detection, saved reports |

The payroll/HR module was layered separately:

| Tier | Scope |
|------|-------|
| 1 | Onboarding checklists, time entries, PTO |
| 2 | Deductions, garnishments, gross-up calculator |
| 3 | Tax forms (W-2/W-3/940/941), employee self-service portal |
