# Payroll / HR Module — Tier 1-3

The payroll/HR module is layered in tiers so the surface area grows
intentionally rather than as a sprawl. This document is the reference for
what's in each tier, where each piece lives, and what's still pending.

## Status snapshot

| Layer | What it covers | Backend | Admin UI | Tests |
|-------|----------------|---------|----------|-------|
| **Tier 1** | Onboarding checklist, time entries, PTO policies/requests | ✅ | ✅ | ✅ |
| **Tier 2** | Deductions (401k, HSA, etc.), garnishments | ✅ | ✅ | ✅ |
| **Tier 3 — Tax forms (JSON)** | W-2, W-3, Form 940, Form 941 endpoints — machine-readable | ✅ | ✅ | ✅ |
| **Tier 3 — Tax forms (PDF)** | WeasyPrint-rendered, employer-branded, audit-hashed | ✅ | ✅ | ✅ |
| **Tier 3 — Document audit hashes** | Per-document SHA-256 in PDF footer + `document_audits` as a linked hash chain with signed, exportable checkpoints | ✅ | ✅ | ✅ |
| **Tier 3 — Portal** | Token-accessed self-service for pay stubs, W-4, bank, PTO | ✅ | n/a | ✅ |
| **Tier 3 — Portal cookie session** | URL token only at first claim; subsequent navigation is cookieless | ✅ | n/a | ✅ |
| **Tier 3 — Portal hardening** | Expiration, no-referrer, rate limiting, employer branding | ✅ | ✅ | ✅ |
| **PTO year-end carryover** | Batch endpoint applies policy carryover caps + resets YTD | ✅ | n/a | ✅ |
| **Time-entry → pay-run auto-population** | Pay-run form checkbox pulls approved unpaid hours | ✅ | ✅ | ✅ |
| **50-state withholding** | Table-driven engine + per-state SUTA rates/wage bases | ✅ | n/a | ✅ |
| **Local/municipal taxes** | PA EIT+LST, OH muni+SD, NYC/Yonkers, MD/IN county, KY, MI | ✅ | n/a | ✅ |
| **Quarterly SUI** | Per-employee wage report, JSON + audit-hashed PDF | ✅ | ✅ | ✅ |
| **E-file exports** | EFW2 (SSA Pub 42-007) + IRS Pub 1220 1099-NEC | ✅ | ✅ | ✅ |
| **Deposit schedule** | Pub 15 lookback, $100k next-day, FUTA floor, liability calendar | ✅ | ✅ | ✅ |
| **Contractor pay runs** | Batch pay 1099 payees, JE + NACHA, feeds 1099 totals | ✅ | ✅ | ✅ |
| **Pay schedules** | Anchored calendars, cutoffs, weekend shifting | ✅ | ✅ | ✅ |
| **Retro pay / proration** | Mid-period salary blend + retro shortfall staging | ✅ | ✅ | ✅ |
| **Termination** | Per-state final-paycheck deadlines + PTO payout staging | ✅ | ✅ | ✅ |
| **Garnishment remittance** | Agency payees + pending register + mark-remitted | ✅ | ✅ | ✅ |
| **Tipped wages** | Top-up guarantee, tip taxation, Form 8846 | ✅ | n/a | ✅ |
| **Work locations** | First-class jurisdictions with validated state/locality | ✅ | ✅ | ✅ |
| **Benefits / ACA / COBRA** | Plans, enrollment, dependents, 1095 data, COBRA notice | ✅ | ✅ | ✅ |
| **Workers' comp** | Carrier class rates + premium-audit report | ✅ | ✅ | ✅ |
| **E-signature** | Envelopes sealed into the document-audit ledger | ✅ | portal | ✅ |
| **Org chart / reviews** | Manager tree, team PTO calendar, review lifecycle | ✅ | ✅ | ✅ |
| **Payroll reports** | Journal, deduction register, contractor payments | ✅ | ✅ | ✅ |
| **Migration parity** | `alembic upgrade head` verified against model metadata | ✅ | n/a | ✅ |

899 tests across the full suite (898 pass, 1 skips without PostgreSQL).

State coverage went from 4 states (WA/CA/NY/OR, hand-written) to all 50 plus
DC. The other 47 are driven by reviewable JSON tables — see
[state-tax-tables.md](state-tax-tables.md), and note that every table ships
unverified until an operator checks it against the state's published guide.

---

## Tier 1 — Onboarding, time, PTO

### Models

| File | Class | Purpose |
|------|-------|---------|
| `app/models/hr.py` | `OnboardingChecklist`, `OnboardingTask` | 8-task new-hire checklist with sign-off |
| `app/models/time_entries.py` | `TimeEntry` | Per-day hours with state, approval status |
| `app/models/pto.py` | `PTOPolicy`, `PTORequest`, `PTOAccrual` | Policy definitions, requests, YTD balances |

### Routes

| Method + Path | Handler | Purpose |
|---------------|---------|---------|
| `GET /api/onboarding/{emp_id}` | `onboarding.get_checklist` | Fetch checklist (seeds if absent) |
| `POST /api/onboarding/{emp_id}/seed` | `onboarding.seed_checklist` | Reset / re-seed standard tasks |
| `PUT /api/onboarding/tasks/{task_id}` | `onboarding.update_task` | Mark signed / complete |
| `POST /api/onboarding/tasks/{task_id}/complete` | `onboarding.complete_task` | Convenience for the SPA checkbox |
| `GET /api/onboarding/{emp_id}/new-hire-report` | `onboarding.new_hire_report` | JSON for state new-hire reporting |
| `GET /api/onboarding/{emp_id}/new-hire-report/pdf` | `onboarding.new_hire_pdf` | Downloadable PDF |
| `GET /api/time-entries` | `time_entries.list_entries` | List, filterable by employee/date range |
| `POST /api/time-entries` | `time_entries.create_entry` | Create a time entry |
| `PUT /api/time-entries/{entry_id}` | `time_entries.update_entry` | Edit |
| `DELETE /api/time-entries/{entry_id}` | `time_entries.delete_entry` | Remove |
| `POST /api/time-entries/{entry_id}/approve` | `time_entries.approve_entry` | Manager workflow |
| `POST /api/time-entries/{entry_id}/reject` | `time_entries.reject_entry` | Manager workflow |
| `GET /api/pto/policies` | `pto.list_policies` | All policies |
| `GET /api/pto/policies/{policy_id}` | `pto.get_policy` | Single policy (added during wiring audit) |
| `POST /api/pto/policies` | `pto.create_policy` | New policy |
| `PUT /api/pto/policies/{policy_id}` | `pto.update_policy` | Edit policy (added during wiring audit) |
| `GET /api/pto/requests` | `pto.list_requests` | All PTO requests, filterable |
| `POST /api/pto/requests` | `pto.create_request` | Submit a request |
| `POST /api/pto/requests/{request_id}/decision` | `pto.decide_request` | Canonical approve/reject endpoint |
| `POST /api/pto/requests/{request_id}/approve` | `pto.approve_request` | Alias for `decision(status=approved)` |
| `POST /api/pto/requests/{request_id}/reject` | `pto.reject_request` | Alias for `decision(status=denied)` |

### Frontend

- `app/static/js/onboarding.js` (280 lines) — checklist UI with per-task signature
- `app/static/js/time_entries.js` (220 lines) — entry list + approve/reject buttons
- `app/static/js/pto.js` (250 lines) — policies + requests with workflow buttons

---

## Tier 2 — Deductions & garnishments

### Models

| File | Class | Purpose |
|------|-------|---------|
| `app/models/deductions.py` | `DeductionType` | Catalog: 401k, health insurance, HSA, union dues |
| | `EmployeeDeduction` | Per-employee election with amount + effective dates |
| | `Garnishment` | Court-ordered wage garnishment with priority |

### Routes

| Method + Path | Purpose |
|---------------|---------|
| `GET /api/deductions/types` | List deduction-type catalog |
| `POST /api/deductions/types` | Create custom deduction type |
| `POST /api/deductions/types/seed-standard` | One-shot seed for fresh installs |
| `GET /api/deductions/employee/{emp_id}` | All deductions for an employee |
| `POST /api/deductions/employee` | Enroll an employee in a deduction |
| `DELETE /api/deductions/employee/{deduction_id}` | Remove an enrollment |
| `GET /api/deductions/garnishments` | List, filterable by `?employee_id=...` |
| `POST /api/deductions/garnishments` | Create a garnishment order |
| `DELETE /api/deductions/garnishments/{order_id}` | Cancel an order |

### Frontend

- `app/static/js/deductions.js` (365 lines) — three-section page (types,
  per-employee, garnishments) with add/remove forms

---

## Tier 3 — Tax forms

### Routes

Two endpoint families per form. JSON endpoints are the
machine-readable contract (useful for future e-file integration); PDF
endpoints render through WeasyPrint with the employer's name + EIN in
the header and a tamper-evident audit hash in the footer. The SPA's
"Generate" buttons hit the PDF variants.

| Method + Path | Returns |
|---------------|---------|
| `POST /api/payroll/forms/w2/{emp_id}?year=YYYY` | W-2 boxes 1-6 + employee/employer identifiers (JSON) |
| `POST /api/payroll/forms/w2/{emp_id}/pdf?year=YYYY` | W-2 PDF + `document_audits` row |
| `POST /api/payroll/forms/w3/{year}` | W-3 aggregate across all active employees (JSON) |
| `POST /api/payroll/forms/w3/{year}/pdf` | W-3 PDF |
| `POST /api/payroll/forms/940/{year}` | Form 940 FUTA — first $7K/employee at 0.6% (JSON) |
| `POST /api/payroll/forms/940/{year}/pdf` | Form 940 PDF |
| `POST /api/payroll/forms/941/{year}/{quarter}` | Quarterly FICA aggregation (JSON) |
| `POST /api/payroll/forms/941/{year}/{quarter}/pdf` | Form 941 PDF |
| `POST /api/payroll/forms/sui/{year}/{quarter}?state=XX` | Quarterly SUI wage report, per-employee detail (JSON) |
| `POST /api/payroll/forms/sui/{year}/{quarter}/pdf?state=XX` | Quarterly SUI PDF + `document_audits` row |
| `GET /api/document-audits` | List audit rows (newest first), filterable by `doc_type` + `doc_key` |
| `GET /api/document-audits/{id}` | One audit row — for verifying a PDF by its footer ID |
| `GET /api/document-audits/verify/{content_hash}` | Find rows by full SHA-256 hash |

### Frontend

- `app/static/js/tax_forms.js` — picker for year/quarter, blob-opens the
  response

---

## Tier 3 — Self-service portal

### Models

`Employee.portal_token` (192-bit, from `secrets.token_urlsafe(24)`),
plus expiration tracking:

```python
portal_token = Column(String(64), nullable=True, unique=True)
portal_token_last_used = Column(DateTime(timezone=True), nullable=True)
portal_token_expires_at = Column(DateTime(timezone=True), nullable=True)
```

### Routes — admin (session-authed)

| Method + Path | Purpose |
|---------------|---------|
| `GET /api/employees/{id}/portal-token` | Mint or return existing token + expiry |
| `POST /api/employees/{id}/portal-token` | Rotate token (resets expiry windows) |

### Routes — employee (token-authed, rate-limited)

All return `Referrer-Policy: no-referrer` and `Cache-Control: no-store`.

| Method + Path | Rate limit | Purpose |
|---------------|------------|---------|
| `GET /portal/{token}` | 30/min | Dashboard |
| `GET /portal/{token}/paystubs` | 30/min | List processed pay stubs |
| `GET /portal/{token}/profile` | 30/min | W-4 + address form |
| `POST /portal/{token}/profile` | 10/min | Save W-4 + address |
| `GET /portal/{token}/bank` | 30/min | List direct-deposit accounts |
| `POST /portal/{token}/bank` | 10/min | Add bank account (Fernet-encrypted at rest) |
| `GET /portal/{token}/pto` | 30/min | Balances + request form |
| `POST /portal/{token}/pto` | 10/min | Submit a PTO request |

### Token lifecycle

- **Hard expiry**: 1 year from mint, in `portal_token_expires_at`.
- **Idle expiry**: 90 days since `portal_token_last_used`. Rolled forward
  on every authenticated request, so an active user never trips it.
- **Expired tokens** return `410 Gone`. The admin can issue a fresh one
  via the rotate endpoint.

---

## Admin UI pages

| Route | Page | JS module |
|-------|------|-----------|
| `#/hr/onboarding` | Employee list with completion % | `onboarding.js` |
| `#/hr/time-entries` | Time entries with approve/reject | `time_entries.js` |
| `#/hr/pto` | Policies + pending requests | `pto.js` |
| `#/hr/deductions` | Types, per-employee, garnishments | `deductions.js` |
| `#/hr/tax-forms` | W-2/W-3/940/941 generation | `tax_forms.js` |
| `#/hr/benefits` | Plans, enrollment, dependents, COBRA, ACA 1095 | `benefits.js` |
| `#/hr/team` | Org chart, team PTO calendar, performance reviews | `hr_views.js` |
| `#/payroll/schedules` | Pay cadences, upcoming-date preview, assignment | `pay_schedules.js` |
| `#/payroll/locations` | Work locations, jurisdictions, employee roster | `locations.js` |
| `#/payroll/contractors` | Contractor pay runs, JE posting, NACHA export | `contractor_runs.js` |
| `#/payroll/remittances` | Garnishment remittance register, mark-remitted | `garnishment_remittances.js` |
| `#/payroll/deposit-calendar` | Depositor classification + liability calendar | `deposit_calendar.js` |
| `#/payroll/workers-comp` | Class rates + premium-audit report | `workers_comp.js` |
| `#/payroll/reports` | Payroll journal, deduction register, contractors | `payroll_reports.js` |
| `#/compliance` | Audit hash chain, checkpoints, artifact verification | `compliance.js` |
| `#/employees/{id}` | Details modal with portal/YTD/bank/docs tabs | `employees.js` |

Two workflows are affordances on existing pages rather than pages of
their own: **Retro Pay** (button on `#/payroll` — preview table, then
apply) and **Terminate** (button on active `#/employees` rows — deadline,
PTO payout, staged run).

---

## Pending items

The major Tier 3 work has shipped — tax PDFs with audit hashes, the
cookie-based portal session, PTO year-end carryover, and time-entry →
pay-run auto-population are all live. What's left is in `docs/todo.md`:

- **State tax table verification** — all 47 table-driven states ship
  `"verified": false`. Verify the states you pay in against their published
  withholding guides; see [state-tax-tables.md](state-tax-tables.md)
- **State W-4 allowances** — `exemption_allowance` assumes one allowance
  per employee because `Employee` has no `state_allowances` column
- **E-Verify submission flow** — schema has `everify_case_number` but
  no integration with the federal system
- **CSP nonce mode** — `script-src` still carries `'unsafe-inline'`. The
  inline bootstrap script is already gone from `index.html`, but ~446
  inline event handlers (`onclick=`, `oninput=`, `onsubmit=`) across the
  SPA modules need `'unsafe-inline'` just as much. Nonce mode means
  converting all of them to `addEventListener` wiring — a real refactor,
  not a header flip.
- **Penetration test against a staging deploy** — never done

---

## Where it all lives

```
app/
├── models/
│   ├── hr.py                  # onboarding, employee documents
│   ├── pto.py                 # policies, accruals, requests
│   ├── time_entries.py        # daily hours tracking
│   ├── deductions.py          # types, enrollments, garnishments
│   ├── bank_accounts.py       # encrypted direct-deposit
│   └── payroll.py             # Employee, PayRun, PayStub
├── routes/
│   ├── onboarding.py          # Tier 1
│   ├── time_entries.py        # Tier 1
│   ├── pto.py                 # Tier 1
│   ├── deductions.py          # Tier 2
│   ├── tax_forms.py           # Tier 3 (UI placeholder routes)
│   ├── payroll.py             # Tier 3 — forms endpoints + core payroll
│   ├── portal.py              # Tier 3 — self-service portal
│   └── employees.py           # Cross-cutting: portal-token mint, documents
├── services/
│   ├── encryption.py          # Fernet with v1: versioning
│   ├── pto_accrual.py         # Per-period accrual math
│   └── payroll_service.py     # Withholding, FICA, FUTA, state tax
├── schemas/
│   ├── hr.py
│   ├── pto.py
│   ├── deductions.py
│   ├── time_entries.py
│   └── payroll.py
└── static/js/
    ├── onboarding.js
    ├── time_entries.js
    ├── pto.js
    ├── deductions.js
    ├── tax_forms.js
    └── employees.js           # extended with portal/YTD/bank/docs tabs
```

---

## Related docs

- [security-hardening.md](security-hardening.md) — the production-readiness pass that hardened the portal, encryption, and HTTPS layers
- [wiring-audit.md](wiring-audit.md) — the spider-web audit methodology and the four disconnects we fixed
- [../SECURITY.md](../SECURITY.md) — public security policy / responsible disclosure
