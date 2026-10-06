# TODO / Working Notes

Current work and release gates: [continued October 5 beta checklist](beta-continuation-2026-10-05.md).
The current completed regression has 6,547 passed / 12 conditional skips,
zero failures and 96.92% statement coverage, with head `b7fringe2026105`.
The dated preparation notes below describe earlier snapshots.

> **Earlier October 5 snapshots:** The initial upstream 2.19.0 intake had
> 6,187 passed / 46 skipped; the first completed beta audit had 6,414 passed /
> 12 conditional skips and 96.97% coverage, both at `m3heads2026105`.
> Those results retain their original provenance. Current release gates are
> maintained in the continued checklist.

Internal scratchpad. Not user-facing — the README and CHANGELOG don't
link here on purpose.

**Layout:** open work first (payroll/HR follow-ups, test-coverage gaps,
security/ops, future work), then the shipped archive. Shipped entries
stay because they carry the design rationale and the follow-ups each
feature created — but every one of those follow-ups is also lifted into
the open section at the top, so nothing actionable hides behind a
strikethrough. When something lands, summarize it in `CHANGELOG.md`
under `[Unreleased]` and move its entry down to the archive.

---

## Open decisions — October 6

The pass that found these is recorded in
[production verification, October 6](production-verification-2026-10-06.md),
which also lists the other open decisions (session revocation on logout,
garnishment remittance posting, benefits on a final check).

- **ACH access for bookkeepers (undecided).** The per-user
  `can_access_bank_details` flag (Settings → Users → "Bank details") is
  saved and enforced by `app/services/ach_settings.py`, but it has no effect
  for a bookkeeper: `/api/payroll` is in `_ADMIN_ONLY_PREFIXES`
  (`app/main.py`), so every ACH route answers 403 before the flag is read.
  In practice the flag only distinguishes admins from read-only users. The
  tests pin the 403 (`tests/test_ach_settings.py`) and test `can_access`
  directly. Decide one of:
  1. *Keep admin-only* (current behavior): remove the "Bank details"
     checkbox for bookkeepers, or say beside it that it applies to
     administrators only. Smallest change, and the safest default for files
     carrying every payee's full account number.
  2. *Honor the flag for the ACH routes only:* carve `/api/payroll/ach-settings`
     and the NACHA export (`/api/payroll/{id}/nacha`, `/api/contractor-runs/{id}/nacha`)
     out of the admin-only prefix for a bookkeeper who has the flag, keeping
     the password prompt, masking and audit events already there; the rest of
     `/api/payroll` stays admin-only. Needs the role gate and the flag gate to
     agree on one order, and tests for a flagged and an unflagged bookkeeper.
  Until decided, treat the checkbox as inert for bookkeepers.

## Follow-ups decided September 26 (separate PRs, not this release PR)

- **Typed ORM models.** Pyright reports 1,889 errors (baseline 1,888; 0 new
  call-shape errors after the invoice-edit fix). About 95% come from legacy
  `Column()` declarations pyright cannot type. Convert the models to
  SQLAlchemy 2.0 `Mapped[...] = mapped_column(...)` in its own PR, then add a
  CI gate that fails on any new pyright error beyond the recorded baseline.
- **SQLAlchemy 2.1** (makes `postgresql://` mean psycopg 3) and **ruff ≥ 0.7**
  — held by requirement caps and Dependabot ignores; each needs its own pass.
- **GPT-6 Astra** for Ask SlowBooks needs a Responses API adapter.
- **`claude-haiku-4-5-20251001`** may be retired from October 15, 2026.
- PostgreSQL backups are custom-format dumps named `*.sql`; renaming touches
  the restore filename validation, so change it deliberately.

## Upstream intake and PR preparation — September 14

Release target: the branch now follows upstream 2.19.0 (merged); the local changes remain unreleased.

Final preparation refresh: upstream main still `a1022f8`; retained Docker image
now includes the import-reference boundary fix. Live PostgreSQL boundary/replay
and persistence checks pass, as do 32 frontend tests and formatting/lint.
Fresh image CVE scan reports zero known vulnerabilities. External acceptance,
full accumulated file review and explicit debt decisions remain open; see
`docs/local-readiness-2026-09-20.md`. No commit, push or PR performed.

Final-gate follow-up: fixed real import/reconciliation races. Full Linux run:
4,859 passed, 11 skipped, one runner zombie-process failure; 47 launcher tests
pass with a proper reaper. Later reconciliation change passes focused checks.
Latest image vulnerability scan reports zero; known scanner/type debt and
browser/native/owner/code-review gates remain explicit in current validation.

Latest intake through `a1022f8` is incorporated: Wave full exports, zero-ledger
refusal and repeat-import protection. Verified with 64 importer tests, 32 frontend
tests and live rebuilt Linux HTTP replay checks. See current validation; final
full-suite/accumulated review and external acceptance gates remain open.

Current local issue checklist: [September 20 readiness](local-readiness-2026-09-20.md).

September 20 coverage follow-ups: fixed unsafe repair of unowned empty tables;
focused IIF routes reach 97/97 statements and repair reaches 182/182. Latest
repair group passes 31 tests with PostgreSQL; payroll/remittance/job-costing
group passes 61. These do not replace the full-run snapshot or close the
remaining acceptance gates; see [validation](validation.md).

September 20 final review: Linux/PostgreSQL/OCR coverage snapshot passed
**4,780 tests, 12 documented skips**, with **97.04% statement coverage**.
Final account-parent/log fixes passed 93 affected tests, including SQLite and
PostgreSQL contention; the final image passed 35 live HTTP checks. CodeQL ran
locally with reviewed alerts; typing/static debt and browser/native/owner gates
remain explicit. See [review findings](review-findings-2026-09-20.md). The intake
counts below describe the preceding run, not the final review.

September 20 intake: the next ten upstream commits through `80f2ad8` are
incorporated; focused intake tests pass 74/74 and frontend tests pass 32/32.
The fresh Docker/PostgreSQL HTTP pass made 359 requests with no 5xx responses.
Chrome is not connected to the browser tool, so real browser acceptance remains
open; 300 inventoried API operations still need separate live workflow/provider
fixtures. Full Python regression: **4,755 passed, 31 skipped, zero failed**;
fresh PostgreSQL migration/repair/concurrency group: **33 passed**, no skips.
See the current handoff at the top
of [validation.md](validation.md); September 16 completion language is historical.

September 16 review: all five chart-import/UI findings in
[the cross-layer review](spiderweb-review-2026-09-16.md) are resolved. The
importer passes 21 tests at 100% statement coverage; frontend passes 32 tests;
existing cross-layer and live PostgreSQL gates remain green. The current-tree
full suite passes **4,738 tests, 31 skipped, zero failed** in 14m57s.

Execution order clarified: local integration and focused checks only, then the
large local validation/fix pass, then final documentation with minimal README
changes. No merge, commit, push or PR as part of this work. Historical PR
preparation notes below are future considerations, not current authorization.

Current scope: the **114 upstream-only commits** through `2866c90` and the
nine-commit 2.15 chart-import intake through `719735e` are integrated in the
working tree. Every ledger row now has a semantic disposition. This work is
deliberately uncommitted, so the Git commit graph does not yet reflect the
content intake. Final preflight closed the container-CVE gate: the rebuilt
Alpine runtime image boots on PostgreSQL 17, serves the 2.16.0 health response
and chart template, has no pip module or launchers, and has zero high/critical
Trivy findings. Actionlint and ShellCheck pass. Pyright still
reports 1,830 app diagnostics requiring triage after its concrete flow issues
were reduced. Hosted CodeQL, native/live
validation and the owner choice on License 2.0/contributor terms also remain
open. See `validation.md` for the coverage run, corrected harness failures,
and exact scope; this is not more upstream commit intake.

Handoff checklist: complete the current browser/live workflow gates, then
external validation plus final uncommitted diff and owner
review. Keep this branch uncommitted until that review is complete.

- September 15 CI preflight: 97% application statement coverage with PostgreSQL
  and OCR available; the full run's five missing-checkout-file failures passed
  focused reruns. Expanded CI lint/frontend coverage, repaired backup failure
  cleanup and whitespace-safe retention, moved the production image to Alpine
  and removed build-only pip, and restored editor type diagnostics. Python
  dependency audits, formatting, frontend, actionlint, shellcheck and final
  zero-high/critical container scan pass.

- September 15 accumulated closeout: standardized operator-entered currency at
  two decimal places without reducing quantity, percentage, FX or inventory
  precision; fixed cross-owner bill/batch allocations and Undeposited Funds
  overdraw/concurrency protection. Latest broad local suite: **4,738 passed,
  31 skipped, zero failed**; frontend **29 passed**; Black 720 files, Ruff and
  whitespace clean; dependency audit clean; production image built and became
  healthy on PostgreSQL 17. Remaining public-release gates require native,
  provider, accessibility, payroll-jurisdiction, penetration, capacity or
  hosted-review environments.

- September 15 fresh review: fixed fractional-cent customer/vendor credit
  applications and inventory reversals after tracking-setting changes for bills
  and both credit types. Twelve regression cases reproduced the defects before
  their fixes. Overlapping focused gates passed 69 and 53 tests; see
  `validation.md` for sequence and scope. Full release readiness is still open.

- September 15 invoice reversal follow-up: fixed tracking-toggle stock errors
  and historical COGS/account drift when voiding edited invoices. Eight new
  cases and the affected regression group passed **111 tests**; original
  movements and journal lines now determine the reversal. Details are in
  `validation.md`; this does not replace the historical full-suite result.

- September 15 final exact-tree regression: **4,566 passed, 31 skipped, zero
  failed, two warnings** in 30m27s after the Redis image requirement/guard.
  `pip-audit` found no known vulnerabilities; Black (718 files), Ruff and
  whitespace checks passed.

- September 15 strict production-runtime gate: a disposable TLS PostgreSQL 17
  + Redis + two-worker deployment started healthy with forced HTTPS. The image
  now includes the Redis client required by its documented shared rate-limit
  storage URI; the focused proxy/rate-limit guard passed 14 tests. Synthetic
  containers, network and certificate volume were removed after the check.

- September 15 PR preparation: remote fetch reconfirmed upstream `2866c90`
  unchanged. Docker restart, separate-database backup restoration, three real
  OCR receipts, browser login/Settings/nonprofit switch/sign-out passed.
  QB import missing-journal warnings repaired; 43 focused tests passed. Current
  Black/Ruff/whitespace checks pass. Detailed evidence is in `validation.md`.

- September 15 production-style crawl: current Docker image rendered all 62 SPA
  routes and served all 68 shell assets. A 275-operation safe GET sweep found
  and fixed two invalid-year tax-calendar 500s; it now has zero 5xx responses.
  The 600-test frontend/auth/system/backend-only gate and 42 focused tax/auth
  tests pass. Token/OAuth/provider/send paths remain separate live acceptance.

- September 15 final-tree suite: **4,565 passed, 31 skipped, zero failed, two
  warnings** in 15m01s after the production-crawl validation fix. This replaces
  the earlier 4,564-pass result; Black, Ruff and whitespace checks remain green.

- September 15 executable deployment gates: a fresh PostgreSQL 17 run passed
  38 tests (five deliberate SQLite variants skipped); production Compose fails
  closed for absent required deployment values and resolves with synthetic ones.
  Packaging/launcher/PDF/OCR gate: 76 passed; proxy/rate-limit/Docker/Kubernetes/
  server/PDF/subprocess gate: 71 passed. Native signed artifacts, real proxy TLS
  and live provider accounts still need their target environments.

- September 15 static security closeout: `pip-audit` found no known dependency
  vulnerabilities; secret scan found test fixtures only; Bandit had zero high
  findings. The reviewed medium findings have fixed origins/allowlisted inputs
  and their AI/encryption/FX/PDF/subprocess/repair gate passed 164 tests (two
  PostgreSQL skips already covered by the fresh-server run).

- September 15 mechanical closeout: JS, workflow YAML, JSON, shell syntax and
  Python compilation passed; `git diff --check` and `git fsck --no-dangling`
  are clean.

- September 15 Docker smoke: isolated Compose build/install passed with
  PostgreSQL 17, all migrations, 57-account seed, first-run setup/login, and a
  live customer→invoice create/fetch flow. Containers and network are stopped;
  synthetic project volumes remain for repeatability.

- September 15 full-suite closeout: after triage and minimal fixes, **4,564
  passed, 31 skipped, zero failed, two warnings** across 4,595 tests in 14m31s.
  Frontend remains green at 29 passed. The full-suite execution gate is closed
  for this tree; native artifacts, live providers and deployment capacity remain
  separate release gates.

- First full-scope security/company batch: donor-template credential exposure
  reproduced and fixed from `2fd6758`; PostgreSQL migrate/seed initialization
  integrated from `dba2839`. Gates: 64 and 110 tests passed respectively.
  The final editable-invoice renderer is now covered by the shared redaction
  path; the September 15 full-suite result supersedes its earlier deferral.

- Further local groups integrated with focused evidence in the ledger: typed
  error handling/QBO callback, control-account protection and account cleanup,
  invoice-message payloads, Wave export headers, shared clipboard behavior,
  PDF logos/WeasyPrint 70 lazy data-only fetcher, portable attachment paths,
  contrast/hidden-state fixes and sidebar update visibility. No full-suite claim.
  Banking's coordinated migration/register/posting/reconciliation group is now
  integrated with local row-lock and account/date-isolation adaptations. Gates:
  25 passed and 98 passed/four PostgreSQL skips; migration tested on disposable
  SQLite only. Source-link navigation and void line-lock gaps are now fixed
  (32- and 33-test Python gates, 27 frontend checks). Matching/void concurrency
  review and later follow-ups remained open at that checkpoint; the later real
  PostgreSQL and seeded-browser gates below supersede those two deferrals.
  Batch claims and the matching/void lock inversion now have guards and real
  PostgreSQL checks: expanded local gate 80 passed; live locking/accounting gate
  13 passed, five SQLite variants skipped. Cash-flow commits 43414fb/ab35f72 and
  wrapper d853dc9 are integrated. Later disposable PostgreSQL parity/concurrency
  and seeded Banking browser gates supersede those deferrals; the temporary test
  databases were removed.
- Native PDF scanning runtime/status/dependency and follow-up WinRT/ImageIO
  fixes integrated: 146 focused tests passed, including real Poppler rendering.
  Existing intake/storage/conversion guards retained. Native artifact acceptance
  and remaining release/launcher changes are still separate ledger items.
- Headless selection persistence and URL/image error wording now integrated;
  49 launcher/OCR-region tests passed (two native-tool skips), plus 64 AI
  transport/security tests. TLS and cleanup safeguards retained. Windows
  version-resource/workflow and macOS release follow-ups remain open.
- Windows version-resource/workflow integration now passes its 15-test focused
  gate; native Windows artifact verification remains open. App version unchanged.
- macOS `a38cca2` failure diagnostics now integrated (20 mocked release/packaging
  tests passed); later timestamp/provenance follow-ups remain in the ledger.
- Timestamp/provenance `79150e3` now integrated (27 mocked packaging tests).
  Control-account docs reconciled; `58870d5` factory reuse adopted while
  retaining lifespan execution. Combined fixture/audit/control/banking/desktop
  gate: 101 passed. Native acceptance and full-suite/memory profiling remain open.
- WebView2-missing guidance/browser fallback and `0a078c2`'s opt-in Windows
  timer lifecycle are integrated (49 focused tests); native Windows acceptance
  remains open.
- Guarded anyio closed-loop cleanup and the UTF-8 test-read follow-up are
  integrated (57 focused tests). Full-suite memory measurement remains deferred.
- Vendor credits and the adapted migration join are integrated; schema repair
  now uses a disposable SQLite revision baseline before dropping only leaked,
  empty blockers (44 combined tests). Real PostgreSQL recovery now reuses the
  existing enum safely, drops only verified empty pending children before their
  parent, and refuses populated dependents; recovery/refusal gates passed.
- Saved invoice-email templates now drive preview and send through one sandbox;
  unsaved previews, redaction, escaping and request-local blank reporting pass
  67 focused tests. A cross-cutting audit found and fixed the missing invoice-
  dialog caller; the dialog now shows the saved-template preview and debounced
  note refresh in a sandboxed `srcdoc` iframe. Focused repair and fallback gates
  passed 49 and 58 tests; a seeded browser visibly exercised the same preview.
  Live SMTP remains open.
- Windows portability CI and the corrected pre-analysis macOS HarfBuzz exclusion
  are integrated (35 focused tests); hosted/native execution remains open.
- Company vocabulary now reaches server responses, control guidance, AI labels
  and document-generated ledger/provider references (82 focused tests). The
  hardened seeded live walk covered 2,862 business/2,853 nonprofit strings with
  zero source-backed leaks or unclassified dynamic results.
- Before full-suite execution, all 4,595 Python tests collected successfully.
  The 29-test frontend gate found and closed an AI Settings regression:
  Custom again starts with its required, 255-character model field visible, and
  the UI names both self-hosted-gateway and custom-endpoint choices. The related
  137-test AI gate passes.
- Sign-out now returns to the desktop picker, active usernames are listed before
  sign-in, and first launch auto-opens the last company until the picker is
  explicitly requested. The combined sign-in/desktop gate passed 67 tests.
- Parked accountant-sharing and Canada notes are integrated into an adapted
  design index. Release/README wrappers are dispositioned without inflating the
  README; obsolete storage-internals provenance is removed.
- License 2.0, contributor terms, and the dependent first-run/installer terms
  remain intentionally unapplied pending explicit owner legal acceptance.

- Integrated `9bfc378`, `fe44ddf`, `20689c9`: comment-only provenance cleanup
  in IIF export, CSS, backup script and JS. Corrected the clock comment to
  match the actual 60-second interval rather than copying the upstream typo.
- Adapted `12102d6` / `61a9aa1`: preserve the light README and exclude unaccepted
  legal claims while retaining applicable contribution/release guidance.
  `7978419`'s fixture convention is incorporated with the sign-in feature suite.
- Before PR: recheck upstream's target SHA and compare the final behavior/diff;
  the pinned 114-commit inventory is fully dispositioned, not merged by ancestry.
- A committed-tree merge preview at local `52721f3` / upstream `2866c90`
  reports seven conflicted paths: CHANGELOG, README, app/main.py,
  app/routes/attachments.py, app/routes/banking.py, desktop_launcher.py and
  docs/data-model.md. It excludes uncommitted work; 14 upstream-changed paths
  also overlap local tracked edits. No merge was performed.
- Resolve the integration baseline before final validation. A full merge
  would also need a migration-head join (`fb23cd45ef67`, `f8a9b0c1d2e3`),
  preservation of local TLS/concurrency safeguards, and fixture compatibility
  checks. Do not rewrite published migration history or use production data.
- Review the accumulated diff, agree PR split/scope and contributor terms,
  validate subsequent fixes on the final tree, then prepare approved
  commits and the PR. No sign-off, push or PR submission has been authorized
  by the intake itself.

## Open work — payroll/HR follow-ups

Bank-import follow-up: BoA parser/fixture/bounds/docs and explicit import-button
recovery now integrated (50 Python + 29 frontend tests passed). The associated
opt-in Windows timer is also integrated. See the ledger for exact dispositions.

Every item below was created by a shipped feature and is currently
recorded only inside a struck-through entry further down this file.
Pulled up here so the open surface is visible in one place.

**Blocking real payroll use — data verification:**
- **Paid-leave caps:** Connecticut and Minnesota caps are corrected and boundary-tested.
  CO/MA/DE now use the verified 2026 Social Security base of 184,500. Employer
  size tiers and exemptions remain unmodelled. Standard Oregon Paid Leave is
  implemented; size, equivalent-plan and localization rules remain open.
  See `docs/state-tax-tables.md`.
- **Payroll processing and historical records.** Immutable benefit snapshots
  supply FICA/FUTA YTD. New drafts serialize payroll writes and refuse stale
  paid history; cancellation refunds verified reservations for restaging.
  Explicit ordinary taxable employer contributions now supply tax wages and
  immutable reports. Migration `b7fringe2026105` adds the nullable classification
  without reclassifying old codes. Missing legacy snapshots, historical bad
  withholding, unverified retro earnings/partial periods and special fringe
  rules remain release limits. See the continued October 5 beta checklist.
- **Independently verify state withholding for supported deployments** — the
  current `StateSpec` data lives in `app/services/state_tax/tables.py`, not JSON
  with a `verified` flag. It records a prior 2026-09-03 verification claim and
  known simplifications; this validation pass did not reverify every figure.
  See `docs/state-withholding.md`.
- **Verify local-tax data** — locality JSON files still carry verification
  flags. Check each jurisdiction used; see `docs/local-taxes.md`.
- **Verify e-file acceptance** — the October 5 corrections checked EFW2 RW/RT
  wage fields against official positions. Complete current-year EFW2 / Pub 1220
  validation and AccuWage acceptance remain open.

**Missing schema dimensions (each blocks a named feature):**
- **State allowances — implemented:** model, request/response schemas, payroll
  calculation, and allowance regression tests exist. Validate state-specific
  inputs and formulas; do not treat the column as missing.
- **Department / job-cost dimension** — payroll reports can't allocate
  by department without it.
- **Gross-receipts tracking** — Form 8027 (allocated tips) needs it.
- **ACA offer codes + affordability safe harbors** — offers aren't
  modelled, so 1095-C lines 14-16 can't be derived.
- **Full SSNs for EFW2** — the app stores last-4 only, so the
  transmittal zero-fills. Also needs a TCC config field.

**Feature gaps with a known shape:**
- **Per-locality W-2 box 20 split** — multiple localities currently
  join into one line.
- **1095-C PDF + AIR e-file** — JSON derivation ships; rendering and
  transport do not.
- **Child-support e-IWO / NACHA CCD+ addenda** — remittance register
  tracks the money but emits no agency-facing file.
- **MI residence credit cap + LST low-income exemption** — documented
  simplifications in the local-tax engine.

**Needs an outside party:**
- **E-signature past counsel** — before relying on it for I-9s
  specifically (federal e-signature rules).
- **Penetration test against a staging deploy** — external scope.

---

## ⚠ Test coverage gaps — models without direct test imports

Historical audit note (not a current coverage measurement): the audit found
20 models that weren't directly imported by any test
module. Most are exercised indirectly through their API routes (a
`POST /api/bills` test exercises `app/models/bills.py`), but no test
imports the model class and pokes its constraints / defaults / hybrid
properties directly. That's a real risk surface: subtle regressions
in constructors, computed columns, or relationship cascades can ship
silently.

**Priority — financial integrity (test these first):**
- `app/models/credit_memos.py` — reversing journal entries, balance math
- `app/models/recurring.py` — schedule generation, next-occurrence math
- `app/models/deductions.py` — pre/post-tax classification affects pay-run math
- `app/models/purchase_orders.py` — convert-to-bill workflow

**Priority — HR / payroll adjacent:**
- `app/models/hr.py` — onboarding tasks, employee documents
- `app/models/tax.py` — tax-rate snapshots used by historical reports

`app/models/time_entries.py` is no longer in this gap: direct portal/payroll/job
tests now exercise its approval state machine, bounds, locks, and pay-run linkage.

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

## Shipped — payroll/HR (kept for the design notes)

Measured against a full-service provider (Gusto et al.). Everything below
has shipped — backend, admin UI, and tests. Anything needing an external
API — ACH origination, EFTPS remittance, e-file transport, carrier feeds —
was deliberately left out of scope; what shipped is computation, records,
and files the operator submits themselves. Entries keep their design notes
and their follow-ups (all of which also appear in the open section above).

- ~~**50-state withholding**~~ — DONE: table-driven engine + 47 Python state specifications
  + per-state SUTA rates and wage bases. See `docs/state-tax-tables.md`.
  Follow-ups it created:
  - **Verify the tables** — independently check the jurisdictions used;
    the current source records a prior verification claim, not JSON flags.
  - **State W-4 allowances** — implemented; validate jurisdiction-specific
    rules and input dimensions (including Illinois Line 2 allowances).
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
  date-sorted liability table. Federal deposit deadlines include recurring
  D.C. legal holidays and the semiweekly three-business-day extension;
  annually verify Publication 15 for one-off holidays or legal changes.
- ~~**Contractor pay runs**~~ — DONE: `/api/contractor-runs` (batch create
  → process JE → NACHA), `VendorBankAccount` (Fernet-encrypted, one active
  per vendor), contractor payments join bill payments in 1099-NEC totals.
  Processed runs can be voided with a row lock and reversing JE; the UI warns
  that accounting reversal cannot recall ACH already sent. SPA page at
  `#/payroll/contractors` — create runs, add
  payees, process (posts the JE), NACHA export modal.
- ~~**Pay-schedule object**~~ — DONE: `/api/pay-schedules` CRUD + upcoming
  preview + employee assignment (syncs pay_frequency). Non-business-day
  shifting includes Federal Reserve holidays and per-schedule blackout dates.
  SPA page at `#/payroll/schedules` — list, create, edit, preview upcoming
  dates, and assign employees.
- ~~**Retro pay / mid-period proration**~~ — DONE: day-weighted salary
  blend via `rate_change_date`/`old_rate` on the stub input;
  `POST /api/payroll/retro-pay/preview|apply` (apply raises the rate and
  stages a draft off-cycle supplemental run). Clawbacks (negative retro)
  deliberately rejected. SPA affordance: Retro Pay button on the Payroll
  page (preview table + apply).
- ~~**Termination + final paycheck**~~ — DONE:
  `POST /api/employees/{id}/terminate` — state deadline rules (CA
  immediate/72h shape, ~16 states listed, rest default next-payday),
  PTO payout at the hourly-equivalent rate staged as a draft off-cycle
  run, deductions deactivated, portal token revoked. Rules are
  approximate — verify against the state labor department. Sick payout
  is opt-in. SPA affordance: Terminate button on active Employee rows
  (modal shows deadline, payout, and staged-run id after termination).
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
  (`#/hr/benefit-coverage`) — plans, enrollment, dependents, the ACA month grid
  with 1094 counts, and COBRA. The COBRA button appears only for an ENDED
  MEDICAL enrollment, mirroring the server rule rather than letting the
  operator discover it through a 400. Follow-ups: 1095-C PDF + AIR e-file,
  ACA offer codes / affordability safe harbors (offers aren't modelled),
  Employee termination now ends open, already-effective enrollments on the
  operator-selected coverage date and flags future enrollments for review.
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

## Security / ops — open

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
     existing 8-provider BYOK config in `app/services/ai_service.py`) to
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
- **Stripe upgrade / checkout** — `POST /api/stripe/create-checkout-session`
  ready; surfacing requires a pricing-page + plan model. Single-tier today.

### Recently wired (was dark-endpoint backlog)
- ~~Portal time-entry submit flow~~ — DONE: ownership-scoped `/portal/time`
  lists the employee's entries and submits draft/rejected rows for approval.
  Approved/paid entries cannot be downgraded through the generic endpoint.
- ~~Portal Documents route precedence~~ — DONE: the cookieless Documents page
  is registered before `/portal/{token}`, so `documents` is not parsed as a token.
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
