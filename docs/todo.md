# TODO / Working Notes

Internal scratchpad for things we know we need to do but haven't shipped
yet. Not user-facing — the README and CHANGELOG don't link here on
purpose. When something on this list lands, move it to `CHANGELOG.md`
under `[Unreleased]` and delete it from here.

---

## ⚠ Test coverage gaps — models without direct test imports

The audit found 20 models that aren't directly imported by any test
module. Most are exercised indirectly through their API routes (a
`POST /api/bills` test exercises `app/models/bills.py`), but no test
imports the model class and pokes its constraints / defaults / hybrid
properties directly. That's a real risk surface: subtle regressions
in constructors, computed columns, or relationship cascades can ship
silently.

**Priority — financial integrity (test these first):**
- `app/models/credit_memos.py` — reversing journal entries, balance math
- `app/models/recurring.py` — schedule generation, next-occurrence math
- `app/models/banking.py` — reconciliation state, bank-transaction matching
- `app/models/deductions.py` — pre/post-tax classification affects pay-run math
- `app/models/purchase_orders.py` — convert-to-bill workflow

**Priority — HR / payroll adjacent:**
- `app/models/hr.py` — onboarding tasks, employee documents
- `app/models/time_entries.py` — approval state machine, overtime math
- `app/models/tax.py` — tax-rate snapshots used by historical reports

**Lower priority — config / admin:**
- `app/models/settings.py`, `app/models/audit.py`, `app/models/backups.py`,
  `app/models/companies.py`, `app/models/email_log.py`,
  `app/models/email_templates.py`, `app/models/bank_rules.py`,
  `app/models/budgets.py`, `app/models/qbo_mapping.py`,
  `app/models/saved_reports.py`, `app/models/attachments.py`,
  `app/models/estimates.py`

Coverage strategy: a single `tests/models/test_<model>.py` per priority
item, asserting (a) construction with required fields, (b) defaults,
(c) computed columns / hybrid properties, (d) cascade deletes.

---

## Payroll / HR — still open

Measured against a full-service provider (Gusto et al.), the local-only gaps
are ordered below. Anything needing an external API — ACH origination, EFTPS
remittance, e-file transport, carrier feeds — is deliberately out of scope;
what's listed is all buildable in-repo as computation, records, or files the
operator submits themselves.

- ~~**50-state withholding**~~ — DONE: table-driven engine + 47 JSON tables
  + per-state SUTA rates and wage bases. See `docs/state-tax-tables.md`.
  Follow-ups it created:
  - **Verify the tables** — all 47 ship `"verified": false`
  - **State W-4 allowances** — needs an `Employee.state_allowances` column;
    `exemption_allowance` currently assumes one allowance
- ~~**Local / municipal tax layer**~~ — DONE: `app/services/local_tax/`
  with 32 seeded localities across PA/OH/NY/MD/IN/KY/MI, W-2 boxes 18-20,
  JE + garnishment integration. See `docs/local-taxes.md`. Follow-ups:
  - **Verify the locality files** — all ship `"verified": false`
  - **Per-locality W-2 row split** — box 20 currently joins multiple
    localities into one line
  - **MI residence credit cap** + **LST low-income exemption** — documented
    simplifications
- ~~**State unemployment filings (SUI)**~~ — DONE: generic wage-detail PDF
  (audit-hashed) + JSON at `POST /api/payroll/forms/sui/{year}/{quarter}`
  with optional `?state=XX`. States accept their own layouts, so the PDF is
  a transcription source, not a filing replica.
- ~~**EFW2 / 1099 transmittal files**~~ — DONE: SSA Pub 42-007 EFW2
  (512-char RA/RE/RW/RT/RF) at `POST /api/payroll/forms/efw2/{year}` and
  IRS Pub 1220 1099-NEC (750-char T/A/B/C/F) at
  `GET /api/tax-forms/1099/fire?year=`, both returning the file + a
  warnings list. Follow-ups: SSNs are zero-filled (app stores last-4
  only), no TCC config yet, layouts need verification against the
  current-year specs / AccuWage.
- ~~**Deposit schedule + liability calendar**~~ — DONE:
  `GET /api/tax-forms/deposit-schedule?year=` (Pub 15 lookback →
  monthly/semiweekly) and `GET /api/tax-forms/liability-calendar?year=`
  (941 deposits, $100k next-day rule, de-minimis warnings, FUTA $500
  floor + carryover, return due dates). SPA page at
  `#/payroll/deposit-calendar` — classification cards, lookback quarters,
  date-sorted liability table. Follow-up: federal holidays not modelled
  (weekend-only roll, so at most a day early).
- ~~**Contractor pay runs**~~ — DONE: `/api/contractor-runs` (batch create
  → process JE → NACHA), `VendorBankAccount` (Fernet-encrypted, one active
  per vendor), contractor payments join bill payments in 1099-NEC totals.
  Follow-ups: no void endpoint for a processed contractor run yet (mirror
  the payroll void). SPA page at `#/payroll/contractors` — create runs, add
  payees, process (posts the JE), NACHA export modal.
- ~~**Pay-schedule object**~~ — DONE: `/api/pay-schedules` CRUD + upcoming
  preview + employee assignment (syncs pay_frequency). SPA page at
  `#/payroll/schedules` — list, create, edit, preview upcoming dates,
  assign employees. Follow-ups: holiday calendar (weekend-only shifting
  today), blackout dates.
- ~~**Retro pay / mid-period proration**~~ — DONE: day-weighted salary
  blend via `rate_change_date`/`old_rate` on the stub input;
  `POST /api/payroll/retro-pay/preview|apply` (apply raises the rate and
  stages a draft off-cycle supplemental run). Clawbacks (negative retro)
  deliberately rejected.
- ~~**Termination + final paycheck**~~ — DONE:
  `POST /api/employees/{id}/terminate` — state deadline rules (CA
  immediate/72h shape, ~16 states listed, rest default next-payday),
  PTO payout at the hourly-equivalent rate staged as a draft off-cycle
  run, deductions deactivated, portal token revoked. Rules are
  approximate — verify against the state labor department. Sick payout
  is opt-in.
- ~~**Garnishment remittance**~~ — DONE: agency payee fields on orders,
  auto-created `garnishment_remittances` rows at pay-run processing, the
  pending register (`GET /api/deductions/garnishments/remittances`) with
  agency-missing nagging, and mark-remitted with a payment reference.
  Follow-ups: child-support e-IWO / NACHA CCD+ addenda output. SPA page
  at `#/payroll/remittances` — pending/remitted/all filter, agency-missing
  highlight, mark-remitted with payment reference.
- ~~**Tipped wages**~~ — DONE: reported vs paycheck tips on stubs,
  automatic minimum-wage top-up for hourly tipped stubs, balanced JE
  (reported tips excluded from wage expense — customers paid them), and
  the Form 8846 FICA-tip-credit summary at
  `GET /api/tax-forms/fica-tip-credit?year=`. Follow-up: Form 8027
  (allocated tips) needs gross-receipts tracking the app doesn't have.
- ~~**Multi-location**~~ — DONE: `WorkLocation` (address + state +
  locality + default WC class, jurisdiction-validated), employee
  attachment, and payroll fallback chain (stub override > employee
  explicit > location > default). SPA page at `#/payroll/locations` —
  list, create, edit, employee roster view, assign employees.
- ~~**Blind index for benefit enrollment metadata**~~ — DONE, with one part
  deliberately not done. `app/services/blind_index.py` adds keyed
  deterministic indexes (`HMAC-SHA256(key, "b1|<table>.<column>|<value>")`,
  domain-separated per column, kept in sync by mapper events so no write path
  can forget one) plus `reindex` for key rotation. Applied so that:
  `BenefitPlan.kind` is encrypted and filtered through `kind_bidx` (the ACA
  1095 derivation), and `BenefitEnrollment.coverage_start`/`coverage_end` are
  encrypted with **no** index — their only SQL predicate is
  `coverage_end IS NULL`, which survives encryption, and the
  month-of-coverage rule is a range comparison a blind index cannot answer
  anyway. `employee_id` stays plaintext on purpose: encrypting a foreign key
  gives up the FK, the cascade and the ORM relationship, while a blind index
  over it would still group one person's enrollments by construction — so it
  would trade referential integrity for concealment it does not achieve.
  Residual leak, documented rather than papered over: a blind index over a
  six-value enum exposes bucket sizes, so the largest `kind_bidx` bucket is
  guessably MEDICAL. Closing that needs per-row key derivation, not more of
  this. See docs/hipaa-compliance.md § 164.312(a)(2)(iv).
- ~~**Sign + off-box the audit checkpoints**~~ — DONE: checkpoints carry an
  HMAC-SHA256 signature over `(v, tip_audit_id, tip_chain_hash, row_count,
  created_at, note)` under `AUDIT_CHECKPOINT_SIGNING_SECRET` (no dev default,
  no fallback to the payroll key), verified on every read; `export`/
  `verify-artifact` endpoints plus a
  `python -m app.services.document_audit` CLI produce and check
  self-contained artifacts that verify against the live chain with **no**
  checkpoint row present, so deleting every checkpoint is now a named
  finding. `resign` handles rotation and refuses to back-sign
  never-signed rows. Remaining, and documented as such: the MAC is
  symmetric, so a compromised *application host* holds the signing key —
  an asymmetric signature or an external timestamping/notary service would
  close that, and both need key infrastructure the app deliberately does
  not own.
- ~~**Benefits records**~~ — DONE: plans/enrollments/dependents
  (`/api/benefits`), ACA 1095 coverage derivation + 1094 counts at
  `GET /api/tax-forms/1095?year=` (JSON; any-day-of-month rule,
  self-insured covered-individual listing), COBRA election-notice PDF
  (audit-hashed, 102% premium), and the Benefits SPA page
  (`#/hr/benefits`) — plans, enrollment, dependents, the ACA month grid
  with 1094 counts, and COBRA. The COBRA button appears only for an ENDED
  MEDICAL enrollment, mirroring the server rule rather than letting the
  operator discover it through a 400. Follow-ups: 1095-C PDF + AIR e-file,
  ACA offer codes / affordability safe harbors (offers aren't modelled),
  auto-end enrollments on termination.
- ~~**Workers' comp**~~ — DONE: carrier-quoted `wc_class_rates`
  (per $100 of payroll, supersede-on-re-quote) and the premium-audit
  report at `GET /api/workers-comp/premium-report?year=` grouping wages
  by (state, class); missing rates surface as None + a named list, never
  a silent zero. WA per-hour L&I stays in the WA engine. SPA page at
  `#/payroll/workers-comp` — rates table, new-rate modal
  (supersede-on-create), premium report with missing-rate warnings.
- ~~**E-signature**~~ — DONE: `SignatureEnvelope` freezes body + SHA-256;
  portal signing (typed name + explicit consent) seals
  (hash, signer, timestamp) into `document_audits`; `/api/esign/{id}/verify`
  detects body or signature tampering. Follow-up: run past counsel before
  relying on it for I-9s specifically (federal e-signature rules).
- ~~**Org chart / PTO calendar / performance reviews**~~ — DONE:
  `GET /api/hr/org-chart` (manager tree, cycle-safe),
  `GET /api/hr/pto-calendar?start=&end=` (overlap semantics, pending
  flagged), and `/api/hr/reviews` (draft → submitted → acknowledged,
  draft-only edits, 1-5 rating). SPA page at `#/hr/team` — three tabs:
  org chart (nested manager tree, cycle warning), PTO calendar (windowed
  list), reviews (create/edit/submit/acknowledge).
- ~~**Payroll report library**~~ — DONE: payroll journal
  (`GET /api/reports/payroll-journal?start=&end=`, per-stub columns +
  window totals + GL transaction ids), deduction register
  (`/deduction-register?year=`), contractor payments by path
  (`/contractor-payments?year=`). Workers' comp, liability calendar,
  SUI, and the remittance register live at their own endpoints.
  SPA page at `#/payroll/reports` — three tabs (journal by run,
  deduction register, contractor payments by path).
  Follow-up: department / job-cost allocation needs a department
  dimension the app doesn't have.

---

## Security / ops — still open

- **CSP `script-src` `'unsafe-inline'` removal** — index.html is clean
  as of the bootstrap.js refactor. What's left: the inline `onclick=`
  + inline `style=` attributes in JS-rendered modal HTML across roughly
  two dozen files. Two viable paths:
    1. Per-file rewrite — every `innerHTML = '<button onclick=...>'`
       becomes addEventListener after the assignment. Touches every JS
       file but each change is local.
    2. Delegated dispatcher — one document-level click handler reads
       `data-action` attributes and resolves them via a small registry.
       Less code total, but every modal template still needs updating
       from `onclick=` to `data-action=`.
  Same scope either way. Defense-in-depth, not an active vuln; tracked
  honestly in docs/security-hardening.md.
- **Penetration test against a staging deploy** — external scope,
  can't be done in-repo.

---

## Future work — flagged, not started

- **Activity log / CRM timeline per customer** — calls, emails, meetings,
  in-app notes logged against a Customer and rendered as a unified
  chronological feed on the customer details modal. Likely model: a
  polymorphic `ActivityEntry(entity_type, entity_id, kind, body, occurred_at,
  created_by)`. Rationale: notes-only is too thin; ops teams need to see
  "we called this customer last Tuesday." The audit_log table already
  captures system-level changes — this would be human-entered activity.
- **Email integration** — outbound real send via SMTP / SES / Postmark
  (currently `email_log` records intent but no transport is wired). Once
  transport lands, replies/bounces feed back into the activity log above.
  Will need a per-company SMTP config, bounce-handling webhook, and a
  rate-limit on auto-sent dunning / reminder emails.
- **Inbox watcher — AI-staged inbound email routing.** Higher-order feature
  built on top of the email integration above. The operator authorizes a
  mailbox (Microsoft Graph + Entra ID app registration, or IMAP for the
  self-host path); a background worker polls or subscribes for new mail.
  Each inbound message goes through:
  1. **Parse** — pull obvious refs from subject + body: PO numbers, invoice
     numbers, customer/vendor names, dollar amounts, dates.
  2. **Match** — fuzzy-match parsed refs against live records (the same
     duplicate-detection engine already at `/api/customers/check-duplicate`
     extends to invoice-number + PO-number lookup).
  3. **Classify + sentiment** — pass the body through the AI layer (the
     existing 7-provider BYOK config in `app/services/ai_service.py`) to
     tag intent (payment confirmation / dispute / inquiry / quote /
     unrelated) plus sentiment (positive / neutral / negative). Tag goes
     into the staged record; AI never auto-acts.
  4. **Stage** — write a row to a new `inbound_email_queue` table with the
     parsed refs, matched records, classification, sentiment, and the raw
     message text + attachments. NEVER auto-apply.
  5. **User review** — a "Mail queue" page lists the staged items grouped
     by suggested action (Apply payment / Acknowledge dispute / Reply to
     inquiry / Archive). Operator clicks Confirm; the action fires through
     the existing API (e.g. `POST /api/payments` with allocation derived
     from the matched invoice).
  Differentiator vs Power Apps / Zapier composites: it's one click in your
  bookkeeper, not a six-step automation built in a separate tool.
  Pre-reqs: `inbound_email_queue` table + worker process + per-mailbox auth
  config (Entra app registration walkthrough in setup-mail.md) + a Mail
  queue UI page. Depends on the Email integration item above (shared SMTP
  + IMAP wiring).
- ~~**DocumentAudit (hash-ledger) viewer UI**~~ — DONE: the Compliance tab
  (`#/compliance`, `app/static/js/compliance.js`) surfaces all four questions
  an auditor asks — does this document match its data (hash lookup), has
  anything been removed (chain verify), was the tail truncated (checkpoints),
  and were the checkpoints themselves deleted (paste an exported artifact
  back in). Checkpoint create / verify / export are one click each.
  Containment and signature are reported SEPARATELY, so an unsigned
  checkpoint over a clean chain reads as a setup gap rather than as
  tampering. Driven end-to-end in Chromium including the
  delete-the-tail-and-every-checkpoint case; 12 contract tests in CI.
- **Portal time-entry submit flow** — server endpoint
  `POST /api/time-entries/{id}/submit` exists for employee self-service;
  portal UI page does not.
- **Stripe upgrade / checkout** — `POST /api/stripe/create-checkout-session`
  ready; surfacing requires a pricing-page + plan model. Single-tier today.

### Recently wired (was dark-endpoint backlog)
- ~~Inventory item movement history UI~~ — DONE: "History" button on each
  tracked item opens the movement ledger (ItemsPage.showMovements).
- ~~AP aging report in the Reports menu~~ — DONE: A/P Aging card alongside
  A/R Aging (ReportsPage.apAging).
- ~~Audit log viewer~~ — DONE: already built + nav-linked; fixed so the
  table loads on open instead of staying empty until a filter is touched.
- ~~Bill-payment void~~ — DONE: `POST /api/bill-payments/{id}/void`
  implemented with row-lock, closing-date guard, reversing JE, and
  `is_voided` idempotency. Mirrors the customer-payment void on the AP side.
  6 void-symmetry tests + closing-date guard test cover the new endpoint.

---

## Known small bugs

(none.)

---

## Production walkthrough — discovered, addressed

Findings from the 2026-05-30 live end-to-end production walkthrough.
All addressed; documenting here so the lessons don't get lost.

- ~~Payroll JE unbalanced when liability accounts missing~~ — DOCUMENTED:
  the failure mode (umbrella `2300` plus `2310`–`2360` required for
  per-tax accounts) is now called out in
  `docs/release-checklist.md §3a` with the full table of
  numbers/names/types. The 500 itself is not a bug — the JE balance
  check is doing its job — but the onboarding gap was real.
- ~~Tax rate format ambiguity~~ — `tax_rate` is a decimal fraction
  (`0.086` = 8.6%), not percentage points. Schema rejects values
  outside `[0, 1]`. Consistent across invoices, bills, POs,
  estimates, credit memos, and recurring.
- ~~Bill payment routing~~ — bills are paid via `POST /api/bill-payments`
  (vendor-level), not `POST /api/bills/{id}/pay` (which never existed).
  Mirrors customer payments at `POST /api/payments`.
- ~~PO→Bill convert response shape~~ — returns
  `{"bill_id": N, "message": "..."}`, not a full BillResponse. The
  caller fetches the bill via `GET /api/bills/{bill_id}` if it needs
  the full row.
