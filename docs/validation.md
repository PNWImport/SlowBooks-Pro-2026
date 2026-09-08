# Validation — 2026-09-07

Maintainer record for `claude/main-branch-protection-2tqh90`, starting at
`25126f25635d3ece42ec38a9b25304112484b154`. This records local validation;
it is not a public-release certification or a completed hosted CI run.

## Branch scope

Compared with `e465031`, the `main` revision merged into this branch, the committed
branch changes span 187 files. They add payroll workflows (contractor runs,
schedules, locations, retro pay, remittances, workers' comp, and reports), HR and
benefits coverage, compliance/filing helpers, local-tax support, signed audit
checkpoints, and additional PII protection. The debug fixes below validate and
harden that broader feature set; they are not the whole branch contribution.

## Results

### Endpoint performance and routing

Time-entry, journal, bill-payment, recurring-invoice, e-sign, job-cost, and
garnishment lists now use bounded pagination. Their rendered relationships are
preloaded, including nested job/customer and job-cost dimensions. Payroll run
responses preload benefit snapshots without joining collections into locked
PostgreSQL queries.

The historical post-2.0 changelog claim that "every list endpoint" was fixed
has been corrected: that sweep covered six document lists and clamped only the
routes that already exposed pagination. Later features and older journal,
recurring, and bill-payment paths required the additional work recorded here.

The query regression gate now requires a constant bound instead of allowing the
limit to grow with seeded rows. It covers invoices, bills and payments, purchase
orders, credit memos, estimates, journals, recurring invoices, e-sign, job/time
and PTO, payroll/remittances, nonprofit documents, and in-kind gifts. The
analytics engine remains pinned to exactly ten aggregate SELECTs.

The 18-test query/pagination gate passed. Separate overlapping checks passed 30
job-cost/performance tests, 26 payroll/time/remittance behavior tests, 15 current
wiring/analytics/e-sign tests, and all 556 route-wide authentication/method cases.
Each run emitted one existing test-client deprecation warning. One stale job-cost
test was corrected to use valid 18/6-hour daily entries and assert creation; its
former 30-hour row was correctly rejected but the test ignored that response.
No full-suite run was performed on this still-changing snapshot.

### Sales-tax payment date fix

Reproduced `date: Input should be None`: the route-local request model shadowed
the imported date type. Aliased that type and marked the fix under 2.9.4.
Ten focused payment/report/schema tests passed (one warning), covering explicit,
omitted and null dates, invalid-date rejection without writes, and balanced
sales-tax debit/bank credit entries. Expanded the AST audit across all `app/`
Python modules and field names; no other direct annotation-name collisions
were found. This is a check for this specific bug class, not all validation bugs.
The disposable Docker app received the patched module; no real tax payment
was made and the database was not reset.

### AI provider documentation review

Confirmed eight provider options and the custom Chat Completions adapter;
76 AI integration/security/analytics/nonprofit tests passed with one warning.
Every provider accepts an editable model ID, and Custom requires both a model
and public HTTPS endpoint. Adapter tests cover provider payloads, tool-call IDs,
Custom/Worker DNS pinning, TLS hostname verification, and peer-address checks.
No paid or credentialed external AI calls were made. Docs include endpoint
configuration, key-removal semantics, data-sharing boundaries, and model/live
provider validation limits.

Closed deployment finding: both Compose files now require a stable external
`SETTINGS_ENCRYPTION_KEY`, so replacing the app container does not orphan AI,
SMTP, payment-provider, QBO, or bank-feed ciphertext retained in PostgreSQL.
Focused static checks and a disposable forced-container recreation verified the
same ciphertext decrypts afterward; no real credential was used. Both Compose
files validate with populated inputs and refuse a missing settings key; app
startup rejects a malformed key before accepting traffic. The operations guide
includes the required preserve-before-recreate path for pre-2.9.4 installs.

Docker/encryption/TLS focused result: **110 passed, 1 warning**. A current image
build passed. In a separate project, a synthetic encrypted SMTP setting was
written to PostgreSQL, the app container was force-recreated, and the setting
decrypted afterward. That project's containers, volumes, and test image were
removed; the interactive demo was not changed.

### UI save-refresh follow-up

Additional Chrome checks passed without manual reload:
- Created `DEMO UI Refresh Plan` (other, no MEC, zero premiums); the plan appeared
  immediately and the URL remained `/hr/benefit-coverage`.
- Created `DEMO Weekly UI Check` and assigned Demo10; the assignment dialog
  closed and the employee edit form showed Weekly. Cache invalidation itself
  is covered by the controller test, not directly observable in this UI check.
- Terminated synthetic Demo11 and Demo12 with payouts disabled; both rows showed
  INACTIVE after X and Escape dismissal respectively. No payout was staged.

Closed the termination-dialog follow-up: submission disables immediately,
successful completion replaces the action row with **Done**, and failures
re-enable **Terminate** for retry. A controller test pins duplicate suppression.
Termination also ends already-effective benefit coverage on an explicit plan
end date (defaulting to termination day). Future-dated enrollments are preserved
and returned as review items rather than assigned a fabricated coverage period.

### Contractor run reversal

Contractor run processing and voiding now serialize on the run row. Voids post
an exact, source-linked reversing journal entry, fall out of contractor/1099
totals, and refuse drafts, repeats, or closed periods. The UI states that
voiding the books cannot recall submitted ACH.
Thirty-seven focused contractor/report/page tests passed, plus JavaScript syntax
and whitespace checks.

### Federal deposit calendar

Federal deposit dates now exclude recurring District of Columbia legal holidays,
including observed dates and Inauguration Day. Semiweekly due dates count the
three business days after the deposit period closes, so an intervening holiday
extends the deadline even when the old nominal Wednesday/Friday was open. The
$100,000 rule now aggregates all same-day/period liabilities, allocates each
dollar once, switches a monthly filer to semiweekly, and carries that status into
the following year; quarter-crossing liabilities remain separate. Forty-eight
focused calendar/payroll tests passed. The calendar follows the 2026 IRS
Publication 15 rules; annual review remains required for one-off holidays and
future legal changes.

### Pay-schedule business days

Upcoming pay dates now apply the selected shift direction to weekends,
recurring Federal Reserve Bank holidays, and optional per-schedule blackout
dates. Saturday holidays correctly leave the preceding Friday open; Sunday
holidays close Monday. Schedule-frequency edits propagate to attached employees;
blank/duplicate names, excessive lead times, and inactive assignments are refused.
Twenty-five focused service/API/page tests passed,
along with SQLite upgrade checks, eight PostgreSQL migration-parity checks,
JavaScript syntax, and the ten-test UI controller suite.

### Employee portal time workflow

The cookie-backed portal now lists only the authenticated employee's 100 most
recent time entries and permits submission only for owned draft/rejected rows.
The shared transition uses a row lock and refuses paid, submitted, or approved
entries; generic update/delete can no longer bypass those states. The Documents
page was moved ahead of the token catch-all after reproducing the route-order
collision. Create/update validation also limits the combined daily entry to
more than zero and no more than 24 hours and refuses explicit nulls. Pay-run
processing, approved-time sweeping, and job posting now take database row locks
before their state checks. A 577-test portal/e-sign/auth-gate run and thirteen focused
payroll/job/portal workflow tests passed with one warning each.

### Financial transition integrity

Accounting state changes now lock their source row before checking status and
posting: payroll/contractor processing, invoice/bill/payment/expense/journal and
job-cost voids, estimate/PO conversions, fixed-asset and nonprofit reversals,
garnishment remittance, bank reconciliation, and e-sign transitions. The manual
journal void route now rejects source-owned entries and refuses a second
reversal. Reconciliation toggles accept only transactions from that bank account
through its statement date; bank-balance updates are serialized. Thirty focused
transition tests passed with one warning.

PTO decisions now lock both the pending request and matching accrual before
relieving hours or liability dollars. The decision remains single-use; four
focused PTO hours/liability tests passed with one warning.

Onboarding mutations and performance-review transitions now lock before their
state checks; repeating task completion is idempotent and no longer rewrites its
completion timestamp. Nineteen focused onboarding/review tests passed. A static
AST sweep found no remaining named commit-backed process, void, convert,
approve, reject, complete, dispose, remit, acknowledge, or submit route without
a row-lock call; this is a route-pattern check, not a concurrency proof.

Consolidated portal, banking, expense, invoice, in-kind, fixed-asset, e-sign,
nonprofit, garnishment, and HR touched-module gate: **77 passed, 1 warning**.

Chrome follow-up: browser connection repaired. In a freshly opened demo tab,
completed the synthetic Emergency Contact task for Demo04, Demo05, and Demo06.
After Close, Escape, and X dismissal respectively, each background row showed
1/8 (12.5%) without a page reload. The earlier user-reported stale view was not
reproduced in this tab; this does not establish why their prior tab stayed stale.
Only those three disposable checklist task records were changed by these checks.

Fixed onboarding summary rows remaining stale behind the checklist dialog,
employee termination refreshing only through Done, coverage-plan creation
navigating to the wrong Benefits module, and pay-schedule assignments leaving
cached employee data unchanged. Shared modal dismissal behavior was preserved.

Ten JavaScript controller tests passed with mocked API/DOM, including failed
onboarding saves, a missing parent row, duplicate termination suppression, and
termination retry. Related backend/wiring tests passed with one warning. The
JavaScript tests are wired into CI but hosted CI has not run. These are not
browser-rendering acceptance tests.

The updated JavaScript files were copied into the running disposable demo and
its source copy. The running container has test-only file updates, not a rebuilt
release image; reload the browser to pick them up.

### First-use Docker walkthrough

Built the current working tree in isolated project `slowbooks-firstuse-vkbz2b`
from a disposable source copy, using fresh test secrets and project-scoped
volumes. No existing company data was used. Docker access works via `sg docker`.

- Found a README blocker: copied `.env.example` enables `FORCE_HTTPS=true`,
  redirecting the documented HTTP URL and health probe to an absent TLS listener.
  Added explicit localhost-only `FORCE_HTTPS=false` instructions to both public
  walkthroughs; network TLS defaults were not weakened.
- Found the image health check followed the production HTTPS redirect to a TLS
  listener that intentionally exists only at the external proxy. It now accepts
  the internal 307/308 without following it and still fails on errors/5xx.
- Quoted required-variable expressions in the production Compose environment;
  embedded `:`/URLs previously made the source invalid to standard YAML tooling.
- Both Compose profiles now default to one worker while counters are in memory;
  operators must configure shared rate-limit storage before scaling workers.
- Image build, PostgreSQL startup, migration to `fa12bc34de56`, seed, and container
  health passed after that setting. Host publications were loopback-only.
- The preserved demo database later upgraded to `fb23cd45ef67`; its existing pay
  schedule remained present and the app returned healthy afterward.
- HTTP home/health, first-run setup, repeat-setup rejection, anonymous denial,
  seeded accounts, core lists, synthetic customer creation, and logout passed.
- Recreated both containers without deleting volumes: setup, login, seeded
  accounts, and synthetic customer persisted.
- App UID is 1000; Tesseract 5.5.0 and Poppler 25.03.0 are installed.

This supersedes the earlier Docker-access blocker below. It is an installation
and API smoke test, not full UI acceptance: browser discovery still returned no
connected browser. Payment providers, native platforms, and the final full
regression suite remain separate gates. Build log:
`/tmp/slowbooks-docker-firstuse-build.log`.

### Regression history

Post-merge frozen baseline: **3,150 passed, 3 intentional public-route auth
skips, 1 warning** in 13m 34s, including PostgreSQL and OCR checks. Source
fingerprints matched afterward; the disposable PostgreSQL server was stopped.
Report: `/tmp/slowbooks-postmerge-full.log`.

The source was then unfrozen for Server Edition hardening. Account/session,
desktop, server-mode and upstream CSP regressions passed (138 tests); a separate
transport/session/API-token run passed 19 tests. Counts overlap. These are not
a full-suite pass on the new snapshot. Native Windows task execution, service
permissions and firewall behavior still require validation on Windows.

A subsequent full run was deliberately cancelled during development after
810 passes, 3 skips and 1 warning; it is not a completed validation result.
Its disposable PostgreSQL server was stopped. Development now uses focused
tests; reserve the next full run for the final candidate.

The table below is historical, before owner-main integration and this follow-up.

| Check | Result |
|---|---|
| Full Python suite | 3,088 passed, 11 skipped; 12m 08s, without coverage |
| PostgreSQL 17.11 migration checks | 5 passed, including populated legacy deductions |
| Tesseract/Poppler engine, region, and receipt tests | 42 passed, no skips |
| Live PostgreSQL backup/restore over verified TLS | Passed |
| Ruff, Black, whitespace, JavaScript syntax | Passed |
| Dependency compatibility and vulnerability scan | Passed; no known vulnerabilities found |
| Disposable HTTP smoke test | Setup, core lists, logout, and post-logout denial passed |
| HIPAA hardening follow-up | 198 passed, 1 warning; 71.51s, including seven new audit-redaction cases |
| PDF follow-up | 43 passed, 1 warning; actual COBRA/SUI output reports tagged structure |
| Packaging/entrypoint follow-up | 12 passed, 1 warning; source checks, not an image build |
| State/local-tax follow-up | 132 passed, 1 warning; includes CT/MN cap boundaries |
| Consolidated current-code regression | 385 passed, 1 warning; 84.34s |
| Coverage run (mixed snapshot) | 3,105 passed, 12 skipped, 1 stale-test failure, 53 warnings; 18m 04s; 81.63% line coverage |

The main run lacked PostgreSQL/Tesseract configuration. Separate runs covered
those eight skipped checks; three skips were intentional login-test exclusions
for public payment endpoints with separate authentication. Fixes made while the
full run was in progress were checked with targeted regression runs; their counts
overlap and must not be added to the full-suite total.

The HIPAA follow-up ran after the audit-redaction fix, using in-memory SQLite
and temporary storage. It covered audit redaction, roles, benefits encryption,
encryption coverage, checkpoint signing/integrity, API tokens, authentication,
tier-3 workflows, and API defect regressions. Black, Ruff, whitespace, and local
documentation links passed. The full suite was not rerun for this follow-up.

## Changes verified

- HIPAA follow-up: reproduced plaintext copies of encrypted fields in audit JSON
  using synthetic in-memory data. ORM audit snapshots now redact encrypted
  fields, credential hashes, portal tokens, and settings values across writes.
  Historical audit rows/backups are unchanged; see [HIPAA readiness](hipaa-compliance.md).
- Correct attachment routing, independent upload/backup filenames, and private
  upload authentication, including normalized paths.
- SVG response sandboxing, including cached responses; files are not rewritten.
- Required Compose secrets, strict database TLS modes, rejection of blank
  encryption secrets, and boot wiring-check failure handling.
- Payment allocation restricted to the selected customer's invoices.
- Backup credential decoding, supported TLS options, transactional PostgreSQL
  restores, and reliable failure reporting.
- Boolean parameters in the benefits data migration; legacy deductions and
  employee amounts/caps survive PostgreSQL upgrades. Historical source tables
  are deliberately retained, not candidates for cleanup.
- Auth-test router enumeration and PostgreSQL migration coverage configured in CI.

## Database and demo data

Owner-main integration added merge revision `fa12bc34de56`, preserving both
existing migration branches. An existing benefits migration was repaired
for databases that have not completed it. Back up the actual database and keys,
check its revision, then use `alembic upgrade head` through the deployment's normal
upgrade path. The user's real database was not accessed.

Source-demo loading and a repeat upgrade at head preserved 57 accounts, 8 customers,
13 vendors, 10 invoices, 5 payments, 15 transactions, and 46 transaction lines.
This is not proof of every historical upgrade path. Keep the existing company
file/volume; reseeding is unnecessary. `docker compose down -v` deletes volumes.

## Final follow-up — 2026-09-08

The clean final pass is complete: 3,232 tests passed, 10 skipped, and no failures
(82.35% coverage; matching source fingerprints). All host
OCR skips passed inside the production image, and the Docker first-use,
persistence, security, dependency, formatting, performance, and main-ancestry
checks are recorded in the [final validation ledger](final-validation-2026-09-07.md).
That ledger supersedes the mixed-snapshot caveats below while retaining the
explicit accessibility, payroll-data, platform-signing, external-test, and live
provider release limitations. Concurrent account balances, document-audit
appends, and signature rollback are covered by the final regression suite;
enterprise capacity acceptance remains open.

## Historical requirements before the final pass

- A clean full-suite run on a frozen final snapshot. The coverage run started
  before PDF/cap/build-context edits; current-code regression results are above.
- Broader browser interaction, rendering, and SVG policy verification beyond
  the completed onboarding/HR and first-use walkthroughs.
- Native Windows/macOS packaging and signing checks.
- Live payment/bank integration checks and applicable payroll/tax data verification.
- Review uncovered paths against release risk; measured line coverage is 81.63%.

The coverage run's sole failure was the old, already-loaded PDF call-site guard
(`4 >= 5`) scanning the consolidated source. The current guard and all modified
areas passed in the 385-test run. This explains the failure; it does not turn the
mixed-snapshot run into a clean full-suite pass. Its 12 skips were three deliberate
public-route auth exclusions, two unavailable-PostgreSQL checks, and seven missing
OCR-tool checks. Earlier PostgreSQL/OCR results remain separate evidence.
The focused run's warning is Starlette's httpx test-client deprecation; the
coverage run also emitted source-analysis SyntaxWarnings.

Local reports: `/tmp/slowbooks-final-validation.log`,
`/tmp/slowbooks-final-coverage.json`, and `/tmp/slowbooks-current-regressions.log`.

Docker validation uses the current user's new group through `sg docker`; a fresh
login is still needed for direct CLI access. Native packaging requires
Windows/macOS, and live provider checks need an authorized sandbox account.
No live provider or payment transaction was used in this pass.

PDF generation now shares the tagged-rendering path for COBRA and SUI reports;
plain-PDF fallback remains documented. Docker context excludes local env/key,
SQLite database/sidecar, and uploaded-data files. State-tax docs were reconciled
with the Python implementation; official-source CT/MN cap corrections and
remaining jurisdiction checks are recorded in [state tax tables](state-tax-tables.md).

Run the full suite with `pytest --cov=app --cov-report=term-missing`.
See [development setup](development.md#running-tests) for PostgreSQL and OCR
requirements and [the release checklist](release-checklist.md) for deployment.

Backup behavior follows PostgreSQL's [libpq environment settings](https://www.postgresql.org/docs/current/libpq-envars.html)
and [pg_restore options](https://www.postgresql.org/docs/current/app-pgrestore.html).
