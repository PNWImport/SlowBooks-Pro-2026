# Validation — 2026-09-07

Current results: [continued beta validation October 5 2026](beta-continuation-2026-10-05.md),
6,547 passed / 12 conditional skips / zero failures, 96.92% statement
coverage, including all 47 browser cases and PostgreSQL/OCR. Final-image
payroll, Docker, Kubernetes, HTTPS and recovery checks pass; remaining release
gates are recorded in the checklist. Alembic head: `b7fringe2026105`.
The first beta audit and dated handoffs below retain their historical provenance.

> **Earlier October 5 snapshot:** After upstream 2.19.0 intake, the branch had
> 6,187 passed / 46 skipped and Alembic head `m3heads2026105`. The fresh beta
> results above supersede that validation snapshot; earlier handoffs are retained.

Maintainer record for `claude/main-branch-protection-2tqh90`, starting at
`25126f25635d3ece42ec38a9b25304112484b154`. This records local validation;
it is not a public-release certification or a completed hosted CI run.

## Current handoff — September 26 (2.18.0, upstream through `90ba2b7`)

Upstream 2.16.2–2.17.3 incorporated as a working-tree merge; details in the
[reconciliation log](upstream-reconciliation-2026-09-14.md). Local target is
**2.18.0 unreleased**.

- **Full suite (Linux, SQLite + PostgreSQL 17 migration DB):** 4,959 tests in
  13 file-sharded processes; 4,936 passed, 18 skipped (OCR binaries absent,
  PostgreSQL-only row locks under SQLite, deliberate auth-exempt routes).
  The 5 failures were stale migration-head pins; after updating them (and
  adding a check that no Numeric(12, 2) column survives an upgrade from any
  parent) all 16 migration tests pass. Sharded runs do not produce a combined
  coverage figure.
- **Frontend:** 32/32. **Black/Ruff:** clean over app, tests, scripts,
  packaging and migrations. **pyright:** no new call-shape errors against the
  September 20 baseline.
- **Upgrade of an existing company:** a copy of the September 20 PostgreSQL
  company (revision `ac14bd25ce36`) upgraded in the rebuilt Compose image
  through `a9b0c1d2e3f4` and `c7d1e4a92b30`; all 135 Numeric(12, 2) money
  columns became Numeric(15, 2), none left narrow; the paid invoice and a
  balanced trial balance survived.
- **Live HTTP walkthrough (28/28):** invoice above 9,999,999,999.99; line edit
  keeps job and cost code on the ledger with the same transaction id;
  `status: void` edit refused with the void route named; duplicate keeps line
  job/cost code; payment, credit memo and bill payment to another party's
  document refused, writing nothing; valid payment and bill payment accepted;
  trial balance balanced throughout; TB/GL/P&L/BS CSV and TB/GL PDF download;
  AI catalogue lists the updated models.
- **Found and fixed during validation:** every recomputing invoice edit
  returned 500 (`assert_not_reconciled` signature mismatch between upstream
  code and this branch).

Not covered: browser-driven UI acceptance, live AI provider calls (no API
keys; request shapes are unit-tested), native Windows/macOS builds, hosted CI.
No commit, merge, push or PR.

## Handoff — September 20

The [local GitHub-style readiness checklist](local-readiness-2026-09-20.md)
tracks pass evidence and open issues; no hosted actions are requested.

**Import reference follow-up — September 21 UTC:** reproduced acceptance and
posting of a 101-character source reference on SQLite, despite the database
model's 100-character limit and the replay guard's truncated lookup. Shared
import validation now refuses overlength identities before any posting; lookup
no longer truncates distinct identities. Boundary regressions verify rejection
without journals and successful 100-character import/replay. The focused
migration/replay/Wave/Xero/MYOB group passes **47 tests**, one warning (13.55s);
Black, Ruff and whitespace checks pass. This host SQLite follow-up does not
refresh the full-suite coverage, PostgreSQL execution or retained Docker image.
Browser discovery still returns no connected browser. No staging or commit.

**Final preparation refresh — September 21 UTC:** rebuilt the retained Linux
Compose app with the reference fix; container/source SHA-256 matches
`de90d3479362feae5c4c63b0f61df32ed0f66c5ca4340d5057323958ed5ce796`.
Live PostgreSQL HTTP checks pass: reject 101-character references without
balance changes; import two 100-character references; replay imports zero
with two duplicates and unchanged balances. Re-login, existing paid invoice
and backup persistence pass. An initial probe accidentally constructed
101-character IDs for the valid case; the application correctly refused them,
and the corrected 100-character probe passed. No production correction needed.
Current image manifest: `sha256:af2db784eab700c723a9bcd30bbe6130b03b508424adce64f7093662ba64b2b1`.
Fresh Trivy database/image scan: zero known vulnerabilities at all severities
(third-party SBOM and Alpine EOL-metadata warnings remain). Black 732 files,
Ruff, whitespace and all 32 frontend tests pass. Online upstream main remains
`a1022f8f807faf6259d6428ced90defcbc93be95`; no further intake needed.
No full-suite rerun or new coverage claim. Browser/native/provider acceptance,
accumulated file review and owner/security-debt decisions remain open.
Evidence: `/home/aitest/slowbooks-validation-20260920-vi7IeD/final-preparation/`.

**Final-gate verification — September 21 UTC:** the full frozen Linux run
completed **4,859 passed, 11 skipped, one failed, 443 warnings**, in
1,689.55 seconds (28m09s). The sole failure was the POSIX parent-watcher test:
this test runner used `sleep` as PID 1 without a reaper, leaving the correctly
exited child as a zombie that still answered `kill(pid, 0)`. It reproduced
without a reaper; rerunning with `tini -s` passed **47 launcher/desktop tests**,
including that test. No launcher code changed. Future container CI runs must
use `--init` (production Compose already does). The original nonzero full-run
result is retained, not relabeled as a zero-failure execution.

Snapshot statement coverage: **97.34% (28,734/29,520)**; no branch measurement.
Python 3.13.15, PostgreSQL 17, Tesseract/Poppler and Node were available; pytest
ran unprivileged. Eleven skips: four deliberate public-route exemptions, five
PostgreSQL-only cases' SQLite variants, two on-demand seed accounts. No missing
OCR or Node skips. Debian/Node 18 runner differs from hosted Ubuntu/Node 22;
the separate host frontend group also passes all **32 tests**.

Review reproduced and fixed concurrent import double-posting on both database
backends, and duplicate SQLite reconciliation starts. The full snapshot includes
the import fix; the later reconciliation reservation is verified separately:
**27 accounting/replay tests pass**, plus **23 banking tests**, five deliberate
SQLite-variant skips. Counts overlap; no new aggregate coverage claim is made
for the later edit. See [review findings](review-findings-2026-09-20.md).

Final rebuilt app remains healthy and preserves login, paid invoice and backup;
live Wave import/replay/refusal checks pass. Image
`sha256:3f12cc6442ba1f848cd51ab17a5b2a9f6c462970904ec00f1deeb07f7df4f4e0`
has zero reported Trivy vulnerabilities at all severities (SBOM/EOL metadata
warnings retained). Black 732 files, Ruff, Actionlint, ShellCheck, dependency
consistency and Git integrity pass. Default CodeQL remains 15 Python / 0 JS,
Bandit 0 high / 6 medium / 45 low; Gitleaks has the same three synthetic fixtures.
Fresh Pyright remains 1,888 diagnostics, with the same diagnostic multiset
ignoring shifted lines. None of these nonzero scanner results are hidden.

Evidence: `/home/aitest/slowbooks-validation-20260920-vi7IeD/final-gates/`.
Disposable suite runner/database removed after archiving; the isolated live app
and unrelated services remain. Browser control still unavailable; native/live
provider/capacity acceptance, independent code-owner review and owner decisions
remain open. Upstream rechecked at `a1022f8`; no commit, staging, push or PR.

**Latest upstream intake — September 20 (September 21 UTC):** integrated
`f7b1d49`, `2348a5d`, `a1022f8`; upstream tip rechecked at `a1022f8`.
Wave full-export parsing, all-zero refusal, skipped/duplicate counts and
repeat-import/opening-balance protection are incorporated across six sources.
Upstream release 2.16.1 is recorded; local target remains **2.17.0 unreleased**.
The importer group passed **57 tests**, plus **seven** new cross-source replay
and opening-balance cases (one warning per group); **32 frontend tests** pass.
Black checks **732 files**, Ruff and whitespace checks pass. An initial test
command named nonexistent files; corrected selection ran successfully. The
opening-balance fixture was corrected to include a genuine balanced residual.

Rebuilt the isolated Linux Compose app, retaining its existing synthetic volumes
and encryption secrets. Real HTTP verified two Wave journals importing, repeat
preview/import counting two duplicates without balance changes, rejection of an
all-zero ledger and preservation of the previously paid invoice. Image:
`sha256:ea7e6fcafa8bd88df72038845ca6a1d3a5c65822bc5e37bb264134ca8fc782ab`.
Fresh Trivy vulnerability scan of this rebuilt image reports zero findings at
all severities. Scanner warnings about third-party SBOMs and incomplete Alpine
EOL metadata remain; a zero-finding scan is not a guarantee of no vulnerabilities.
This is sequential replay evidence, not concurrent-import certification.
Fresh dependency audits immediately before intake found no known vulnerabilities
in 69 runtime, 19 development and four Linux-resolved desktop dependencies;
the intake changes no dependency files. Platform-conditional dependencies on
other OSes are not certified by Linux resolution. Full-suite/coverage and browser
acceptance were not rerun; no commit, push or PR. Evidence:
`/home/aitest/slowbooks-validation-20260920-vi7IeD/latest-intake/`.

**Fresh Linux installation — September 20:** built the current working tree
with the documented Docker Compose configuration under the isolated project
`slowbooks-fresh-local`, using fresh volumes, generated encryption/session/DB
secrets and loopback ports 33017 (app) / 35437 (PostgreSQL). This tests the
unreleased local source, not the published installer or a fresh upstream clone.
Automatic migrations reached `ac14bd25ce36`; seed created 57 accounts; version
2.17.0 became healthy. Image:
`sha256:d62cdf4a194698795fd195df721c3b9eaf5a323416e50aaabeed6c73f9a3c8ce`.
The app runs as UID 1000 with a read-only root and all capabilities dropped.

The real HTTP accounting workflow passed 35 requests (credits, transfers and
reconciliation guards); 16 additional requests checked login, HTML/JS delivery,
collections, customer → 51.06 invoice → payment, fractional-cent rejection,
PDF generation (12,244 bytes) and backup/list/download (419,124 bytes).
Unauthenticated account access returned 401. A probe's initial `/customers`
404 was corrected: this frontend uses hash navigation, not that server path.
The actual backup restored successfully into a separate disposable PostgreSQL
database: migration head, synthetic customer and paid invoice/zero balance
verified. App restart and re-login preserved invoice and backup. Real
Tesseract 5.5.2 / Poppler PDF OCR recognized 51.06, returned a 144,433-byte
preview and discarded the temporary intake successfully.

Browser control reported no available browser, including an open attempt;
rendering, clicks and visual usability remain unverified. This is not a full
API sweep, new CVE scan, native desktop install or enterprise certification.
The synthetic stack is retained for inspection at `http://127.0.0.1:33017`;
existing unrelated services and real data were untouched. Credentials remain
in the disposable containers; do not treat this as a permanent deployment or
recreate it with different encryption secrets. Evidence:
`/home/aitest/slowbooks-validation-20260920-vi7IeD/fresh-linux-install/`.

**Coverage-gap follow-up 4 — September 20:** added 13 backup HTTP regression
cases: registered-file download, missing/unregistered files, external symlink
refusal, listing, create/restore result mapping and committed restore intent
surviving a service rollback. All restore calls in the new tests are stubbed;
file fixtures are disposable. The backup-route/service/error group passed
**37 tests**, no skips, with **100% statement coverage (52/52)** for backup
routes and no exclusions. Two SQLite connections in an existing corrupt-file
test now close explicitly. The run still emits SQLite resource warnings;
this is not a warning-free result. No production changes were needed.
Black checks 731 files; Ruff and whitespace checks pass. Evidence:
`/home/aitest/slowbooks-validation-20260920-vi7IeD/coverage-followup-4/`.
No whole-tree coverage or additional live-restore certification is claimed.

**Coverage-gap follow-up 3 — September 20:** added ten payroll HTTP regression
cases. Gross-up rejects zero, negative, fractional-cent and nonfinite targets;
missing employee/run requests return 404. Regular and supplemental quotes for
51.06 preserve cent precision and create no payroll/journal records. Aggregate
supplemental creation passes the prior processed regular run's gross to the
real withholding calculator. The payroll-boundary/Tier-2/gross-up group passed
**39 tests**, no skips, 23 warnings (21.50 seconds). No production changes were
needed. Black checks 730 files; Ruff and whitespace checks pass. Evidence:
`/home/aitest/slowbooks-validation-20260920-vi7IeD/coverage-followup-3/`.
These focused results do not replace the full-suite snapshot or certify the
open browser/native/provider and release gates.

**Coverage-gap follow-up 2 — September 20:** added ten regression cases
for repair inspection/script-read fallbacks, healthy-database detection and
payroll posting guards. The combined SQLite/PostgreSQL repair group passed
**31 tests**, no skips, six warnings (90.71 seconds), reaching **100% statement
coverage (182/182)** for `app/services/schema_repair.py`, without exclusions.
Payroll, garnishment-remittance and job-costing tests passed **61 tests**,
no skips, 39 warnings (35.11 seconds). They verify journal rollback after a
job-costing rejection, missing required accounts leaving runs unprocessed,
and unusable diagnostic entries creating no remittances on a no-withholding
stub. This group exercises 18 statements missed by the full-run snapshot
(including six already covered in follow-up 1); totals overlap earlier runs.
No additional production change was needed. Black checks 730 files; Ruff and
whitespace checks pass. Evidence:
`/home/aitest/slowbooks-validation-20260920-vi7IeD/coverage-followup-2/`.
The disposable PostgreSQL container and its synthetic volume were removed.
Whole-tree coverage, image/scanner freshness and the open acceptance gates
below are not superseded by these focused results.

**Coverage-gap follow-up — September 20:** added 31 focused regression cases
across schema repair, IIF HTTP boundaries and payroll history/rejection paths.
The migration/import group passed **63 tests**, no skips, six warnings, including
real PostgreSQL repair; the payroll group passed **35 tests**, no skips,
20 warnings. IIF routes now have **100% statement coverage (97/97)** in the
focused run; schema repair has **96.15% (175/182)**. Payroll tests exercised
six statements missed by the full-run snapshot. No exclusions were added and
no new whole-tree percentage is claimed.

The tests reproduced a destructive repair boundary: after an already-exists
error, the retry path could drop an empty table not created by any pending
migration. It now refuses that table before considering drops. The regression
uses an actual disposable SQLite table with an injected migration failure;
dependency cycles, populated/external children and retry limits are also tested.
Black checks 730 Python files; Ruff and whitespace checks pass. Evidence is in
`/home/aitest/slowbooks-validation-20260920-vi7IeD/coverage-followup/`.
The full-run, image and scanner results below predate this repair guard.

**Final local review follow-up — September 20:** the Linux CI-equivalent
coverage run passed **4,780 tests, 12 skipped, zero failed, 389 warnings**,
exit 0, in **1,622.82 seconds (27m02s)**. Statement coverage is **97.04%**
(28,605/29,477); branch coverage was not measured. The isolated Debian runner
used Python 3.13.15, PostgreSQL 17 and native OCR/PDF tools, with pytest running
unprivileged. Skips were four deliberately public routes, five PostgreSQL-only
cases' SQLite variants, two on-demand seed accounts and one missing-Node theme
probe. The two theme tests passed separately on the host; frontend stays 32/32.

The review fixed ordinary account-parent cycles/missing parents and diagnostic
log-line forgery. A later contention probe reproduced the SQLite variant of
the parent race; write serialization now protects both database backends.
After that final fix, the affected PostgreSQL/SQLite/account/import/error group
passed **93 tests, two seed-data skips**, and a further account-API group passed
27. These are overlapping follow-ups, not an inflated full-suite total. The
full run used the earlier frozen snapshot; its coverage is not relabeled as
measurement of subsequent edits. The final rebuilt image passed 35 live HTTP
checks plus restart/authentication/persistence; fresh Trivy reports zero
HIGH/CRITICAL findings. Strict runtime/development dependency audits, formatting,
lint, workflow/shell checks and repository integrity checks pass.

Local CodeQL now completed: default suites report **15 Python / 0 JavaScript**
alerts; expanded suites **401 / 11**. Reviewed dispositions, Bandit/Gitleaks
results and the **1,888-diagnostic** Pyright backlog are in
[the final review record](review-findings-2026-09-20.md). Scanner execution is
not a zero-finding pass. Upstream `main` was rechecked at `80f2ad8`; the older
fork `origin/main` is not the intake target. Evidence is archived outside the
repo at `/home/aitest/slowbooks-validation-20260920-vi7IeD/`.
Disposable test containers, their synthetic PostgreSQL volume and internal
network were removed after archiving; existing unrelated services were untouched.

The sections immediately below describe the preceding September 20 intake
and host run. Browser/native acceptance, full workflow coverage, remaining
review/debt disposition and owner release decisions remain open; no PR,
commit, staging, push or merge was performed.

The ten upstream commits after `719735e` through `80f2ad8` are incorporated
as working-tree changes. Upstream has released 2.16.0, so this branch now
targets **2.17.0 (unreleased)**. The intake adds dashboard YTD/trend cards,
month-to-date boundaries, theme redraws, nonprofit phrase casing and desktop
permission-denial tests. Focused intake tests: **74 passed**; frontend: **32
passed**. Black checks **727 files**; Ruff, Actionlint, ShellCheck and whitespace
checks pass.

A fresh image booted on disposable PostgreSQL 17. Live HTTP testing made
**359 requests with zero 5xx responses**, including customer/invoice/payment,
fractional-cent rejection, chart preview/apply/stale-plan rejection, YTD and
balance-sheet invariants, nonprofit card labels and static assets. The OpenAPI
inventory has **574 operations**: the GET sweep exercised 274 (190 successful,
84 rejected or missing fixtures); 300 other operations need separate workflow
or provider fixtures. Those deferred operations are not counted as passing.
Requests ran inside the app container on an internal Docker network.
Six additional authenticated GET checks passed with valid dates/IDs, including
PTO calendar, payroll journal, time summary, dashboard preferences, account
detail and a real invoice PDF (12,332 bytes). Earlier 422 responses on the date
queries came from the probe supplying generic strings, not product failures.
Fresh runtime/development dependency audits found no known vulnerabilities;
Trivy found **zero HIGH/CRITICAL findings**, without excluding unfixed issues,
in `slowbooks-review-217` (image ID
`sha256:6a0c5cc8ce7bcb246dad30fed28352c5028b704a3c779efeec1697a8dc2736e8`).
The fresh PostgreSQL migration/parity, repair and concurrency group passed
**33 tests**, one warning, no skips, in 73.03 seconds. Restarting the app
preserved authentication and the synthetic paid invoice. Git object integrity,
dependency consistency and the single Alembic head (`ac14bd25ce36`) pass.

**Browser gate remains open:** the browser inventory returned no connected
browsers, and selecting Chrome returned `Browser is not available: chrome`.
The earlier reply claiming the requested live Chrome/all-API check was complete
reused historical results; it did not execute that requested new browser crawl.
The September 16 blanket statement that local gates were closed is superseded
by this explicit scope. The preceding host Python regression passed **4,755 tests,
31 skipped, zero failed, 258 warnings** in **898.16 seconds (14m58s)**, exit 0.
The PostgreSQL variants passed separately above; unavailable host OCR tools and
deliberate public-route exclusions remain documented skips. Historical counts
below retain their dates. Disposable app/PostgreSQL containers, synthetic volume
and network were removed; the tested image and local evidence logs remain.

Local evidence: `/tmp/slowbooks-live-review-217-result.json`,
`/tmp/slowbooks-live-review-217.py`, `/tmp/slowbooks-full-20260920.log`.

**Current review status — September 16:** the five reproduced chart-import/UI
defects are fixed with regressions: invalid plans are atomic, apply is bound to
the current reviewed plan, bank/type invariants hold, parent-only changes apply,
and hierarchy cycles are rejected. The importer passes **21 tests at 100%
statement coverage (433/433)**; frontend passes **32/32**. See
[cross-layer review and evidence](spiderweb-review-2026-09-16.md). Earlier
cross-layer groups also passed (583, 257, 119 and 38 tests; overlapping scopes),
including live PostgreSQL migration/concurrency checks. The post-fix expanded
route/auth/wiring, ledger, import and migration gate passed **682 tests** with
six documented skips.

**Current-tree full regression — September 16:** after the five chart-import
fixes and 2.15 intake, the complete local Python suite passed **4,738 tests,
31 skipped, zero failed, 258 warnings** in 14m57s. The environment-dependent
PostgreSQL migration/concurrency cases passed separately in the disposable
PostgreSQL 17 gate above; OCR binary cases passed in the documented container
preflight. This supersedes the September 15 4,715-pass local baseline.

**Final image preflight — September 16:** the exact 2.16.0 Alpine image built
and booted against disposable PostgreSQL 17 using the documented private-network
deployment mode. `/health` returned `ok` with version `2.16.0`, and the shipped
chart template returned HTTP 200 (746 bytes). A corrected runtime probe found
that pip's unusable launcher scripts remained after its module was removed;
the Dockerfile now removes both launchers and module, with a source regression
guard. The rebuilt image reports `PIP_ABSENT` and a fresh Trivy database reports
**zero HIGH/CRITICAL vulnerabilities**. Actionlint and ShellCheck also pass.

## Historical handoff status — September 16 (superseded above)

The September 16 handoff marked local implementation and regression gates closed.
The branch contains upstream intake through `719735e`, targets unreleased
version `2.16.0`, and remains intentionally uncommitted. The final local
handoff set covers the full Python and frontend suites, focused chart-import
coverage, Docker/PostgreSQL health and template smoke, dependency audits,
Trivy, Black, Ruff, Actionlint, ShellCheck, and whitespace validation.

Before opening a PR, review the complete uncommitted diff and run hosted CI.
Remaining external gates are CodeQL, native signed Windows/macOS artifacts,
live provider/bank credentials, jurisdictional payroll review, accessibility,
penetration testing, and sustained enterprise-capacity testing.

## Branch scope

Compared with `e465031`, the `main` revision merged into this branch, the committed
branch changes span 187 files. They add payroll workflows (contractor runs,
schedules, locations, retro pay, remittances, workers' comp, and reports), HR and
benefits coverage, compliance/filing helpers, local-tax support, signed audit
checkpoints, and additional PII protection. The debug fixes below validate and
harden that broader feature set; they are not the whole branch contribution.

## Results

### Coverage follow-up — September 8, after the validation commit

#### Current work queue

- Final CI/security preflight (September 15, Pacific): ran the Python 3.13
  coverage job in Docker with PostgreSQL 17 and real OCR binaries. The full
  run reported **4,728 passed, 11 skipped, five failed, 406 warnings** in
  26m48s, with **97% statement coverage** (28,948 statements, 863 missed).
  All five failures were missing checkout files deliberately excluded from
  the production image: three data-model documentation checks and two Docker
  source-configuration checks. The final rerun of both affected modules plus
  backup regressions passed **25 tests** after supplying those files; this is
  not a claim that the original full run exited successfully.
  Black (**720 files**), Ruff, all **29 frontend tests**, actionlint, shellcheck,
  66 JavaScript syntax checks, five workflow YAML parses, 66 local documentation
  file links, `pip check`, Git integrity and whitespace checks passed. CI now
  checks packaging/migrations and every frontend test file. The backup script
  now reaches cleanup on dump failure and prunes filenames safely when paths
  contain spaces; two disposable-shell regressions passed. The broader updated
  deployment/packaging group passed **79 tests**.
  Runtime and development requirements audits found no known vulnerabilities.
  Bandit found zero high and 13 reviewed medium findings, with no scan errors.
  The redacted secret scan found three intentional test literals and three
  ignored local `.env` values, not tracked production credentials.
  The first Debian image scan found 130 high/critical package findings. The
  final image now uses the supported Python 3.13 Alpine runtime and contains
  the same PDF/OCR/PostgreSQL tools. Removing build-only pip and ensurepip
  removes their vendored packages from the release artifact. Final Trivy scan:
  **zero high/critical findings**. It imported the app, processed a real
  Poppler→Tesseract English receipt fixture, rendered a valid WeasyPrint PDF,
  and migrated/seeded PostgreSQL before becoming healthy; HTTPS forwarding
  returned version 2.9.3.
  Static-flow follow-up (September 15): corrected nullable upload filenames,
  settings-derived estimate prefixes, exception-path QBO identifiers and
  retry-local invoice/recurring descriptions. A second pass made missing-record
  boundaries explicit for payroll, sales receipts, reconciliation, job costing,
  nonprofit control accounts, imported customers and audit artifacts. The
  **178-test** and **82-test** affected groups passed. Pyright now reports
  **1,830 diagnostics in 332 app files**, down from 1,895; every 12 `possibly
  unbound` diagnostic is gone and nullable-member/subscript diagnostics fell
  from 43 to zero. ORM typing dominates the remaining backlog, but blanket
  dismissal is not justified. Removed the local setting that disabled type
  checking. This
  backlog, CodeQL
  on its hosted runner, and native Windows/macOS acceptance remain open.
  Cargo audit is inapplicable: there is no Cargo manifest or lockfile.
  Raw local reports and coverage XML: `/tmp/slowbooks-preflight-zmf8GF/`.

- Latest full-suite regression (September 15): **4,715 passed, 31 skipped,
  zero failed, 258 warnings** in 15m04s. This is the current broad local
  result after the release-preparation changes. The audit key-rotation guard
  added immediately afterward was covered separately by **13 passing audit
  tests**; it does not invalidate the broad result. The documented skips are
  environment-gated PostgreSQL concurrency/repair and OCR binary coverage,
  plus deliberate unauthenticated webhook-route assertions.

- Current-main intake (September 16): integrated the nine commits through
  `upstream/main` `719735e` after the earlier `2866c90` intake. This adds the
  2.15 chart-of-accounts importer, dry-run UI, template and hledger fixtures;
  its **13-test** backend regression suite and the **29-test** frontend suite
  pass, as do Black, Ruff and whitespace checks. Content is intentionally
  uncommitted; no merge, push or PR occurred.

- Next-release metadata (September 16): runtime version and the leading
  in-app release-note entry now target **2.16.0 (unreleased)**. README and
  CHANGELOG distinguish this branch from upstream 2.15.0. Windows version
  resources, macOS build identity and system-route checks: **16 passed**;
  JSON/version alignment and whitespace checks passed. No release tag created.
- Accumulated correctness closeout (September 15): operator-entered currency
  now has one shared two-decimal contract across invoices, bills, credits,
  payments, banking, payroll and the remaining accounting inputs. Whole-dollar
  and cent values such as `0.00` and `51.06` remain valid; fractional cents are
  rejected before writes, while quantities, percentages, exchange rates and
  inventory calculations retain their separate precision. The direct contract
  gate covered **114 cases**. Review also fixed cross-vendor bill settlement,
  cross-customer batch settlement, nonpositive bill/batch allocations, and
  deposits that exceeded Undeposited Funds; deposits now validate availability
  while locking the fund account to serialize concurrent posting. Regression
  scenarios retain journal-balance coverage for fractional quantities that
  calculate sub-cent line totals. The exact final tree passed **4,713 Python
  tests, 31 skipped, zero failed** in 14m58s and **29 frontend tests**. Black
  checked **719 files**, Ruff and `git diff --check` passed, and `pip-audit`
  found no known dependency vulnerabilities. Bandit reported zero high and 13
  reviewed medium findings, all fixed-origin/allowlisted or intentional runtime
  behavior. A fresh production image built and reached healthy status against
  PostgreSQL 17; `/health` reported version 2.9.3. The validation stack was
  stopped with its synthetic volumes retained. Native signed artifacts, live
  providers, accessibility, jurisdictional payroll review, penetration testing,
  deployment capacity and hosted review remain external release gates.
- Invoice reversal follow-up (September 15): four failing cases reproduced
  stock corruption after tracking toggles and incorrect COGS reversals after
  quantity edits at different historical costs. A two-unit sale at $10 followed
  by two more at $20 was voided as four units at $20, leaving a $20 account
  residue; changing the asset account also routed the reversal incorrectly.
  Invoice void now reverses recorded sale/edit movements and their linked
  journal lines, retaining original accounts, amounts and dimensions. Eight
  new cases cover both tracking directions, quantity increases/reductions/zero,
  and asset-account changes. The final affected suite passed **111 tests, one
  warning**, including inventory, invoice posting/void/dimensions/late fees,
  closing-date enforcement, duplication, vendor credits and credit applications.
  Black, Ruff and whitespace checks pass. The accumulated correctness closeout
  above supersedes this focused checkpoint.
- Fresh correctness review (September 15): reproduced **two defect classes in
  12 new regression cases** despite the earlier green suite. Customer/vendor
  credit applications accepted fractional cents (for example, applying $0.001
  returned success while stored balances remained unchanged); both schemas now
  reject amounts with more than two decimal places before writes. Bill,
  customer-credit and vendor-credit voids used today's inventory tracking flag,
  inventing or failing to reverse stock after a flag change. They now reverse
  the original inventory movements and recorded costs. Both tracking directions
  were reproduced through the item-update API for all three document types.
  The bill/inventory/credit group passed **69 tests** before the final
  customer-credit void adjustment; the final credit-focused group passed **53
  tests** afterward. These overlapping groups are not a combined test count.
  Black, Ruff and whitespace checks pass. The **4,566-pass full suite below
  predates these fixes**; this focused review does not establish completion of
  the accumulated-diff review or the remaining release gates. Prior wording
  claiming "100%" applies only to the previously executed checks, not absence
  of defects or production-release readiness.
- Final exact-tree regression (September 15): after the Redis production-image
  requirement and guard, the full Python suite completed **4,566 passed, 31
  skipped, zero failed, two warnings** in 30m27s. The documented skip set is
  unchanged and its PostgreSQL/OCR branches were exercised separately above.
  The amended requirements also passed `pip-audit`; Black (**718 files**), Ruff
  and `git diff --check` are clean.
- Strict multi-worker production runtime (September 15): a disposable stack
  with PostgreSQL 17 over TLS, Redis-backed shared limits, two app workers,
  forced HTTPS and trusted-proxy forwarding started healthy. Plain HTTP returned
  307, trusted forwarded HTTPS returned 200, both workers started, and the live
  limiter reported `RedisStorage` with Redis `PONG`. This exposed a real image
  gap: `RATE_LIMIT_STORAGE_URI=redis://...` was supported but the Python Redis
  client was absent from `requirements.txt`; it is now included and has a
  focused configuration guard (**14 passed**). The synthetic stack was removed
  after verification.
- Mechanical final sweep (September 15): every application JavaScript file,
  workflow YAML, tracked JSON file and shell script parsed successfully; Python
  compilation across app, migrations, scripts and packaging passed. `git diff
  --check` and `git fsck --no-dangling` are clean.
- Final static security review (September 15): `pip-audit` reported **no known
  vulnerabilities** in `requirements.txt`; tracked-secret patterns found only
  intentional test literals and local `.env`/key files remain ignored `0600`.
  Bandit reported zero high findings. Its six medium findings were reviewed as
  fixed-origin/allowlisted dynamic-query or diagnostic code, with the supporting
  AI SSRF, encryption/blind-index, FX, PDF/subprocess and schema-repair gate at
  **164 passed, two PostgreSQL skips**. The PostgreSQL repair branch was already
  executed in the fresh-server gate above. No unresolved static security defect
  remains in this review.
- PostgreSQL and deployment closeout (September 15): a brand-new disposable
  PostgreSQL 17 server ran the skipped migration/concurrency/row-lock/schema
  repair group: **38 passed, five intentional SQLite-variant skips**. Production
  Compose fails closed when required deploy values are absent and resolves with
  synthetic required values. Packaging/launcher/PDF/OCR boundary gate: **76
  passed**; proxy/rate-limit/Docker/Kubernetes/server/PDF/subprocess gate: **71
  passed**. Black, Ruff and whitespace checks remain green. Real signed Windows
  and macOS artifacts, a TLS proxy with a real CA chain, and live provider
  credentials still require their respective environments.
- Final full-suite rerun (September 15): after the Docker crawl's tax-calendar
  validation fix, the current tree completed **4,565 passed, 31 skipped, zero
  failed, two warnings** in 15m01s. This supersedes the earlier 4,564-pass
  result. The skip set is unchanged: isolated PostgreSQL concurrency/repair,
  host OCR binaries, deliberate public-route exemptions and two on-demand
  accounts. Black, Ruff and whitespace checks remain green.
- Production-style Docker crawl (September 15): rebuilt the isolated image from
  the current tree. The real browser rendered all **62 static SPA routes** under
  the synthetic authenticated nonprofit company with no rendered error state;
  its only console error was the expected initial pre-login dashboard request.
  All **68** shell JS/CSS assets returned nonempty HTTP 200 responses. OpenAPI
  lists 283 GET operations: 167 safe parameter-free calls returned no 5xx, and
  a broader input-shaped sweep called **275** while deliberately excluding eight
  token/OAuth flows; 200/204 responses numbered 201 and there were **zero 5xx**.
  Expected 400/401/404/422 responses covered missing inputs, portal auth and
  synthetic unknown IDs. The sweep found invalid `year=1` caused two tax-calendar
  500s through their two-year lookback; both endpoints now validate `year >= 3`
  and return 422, with **42** focused tax/auth tests passing. The real browser
  reloaded the rebuilt image and rendered Opening Balances. A **600 passed,
  four skipped** frontend/auth/system/backend-only suite covers method and auth
  contracts beyond this read-only runtime sweep. External providers, email sends,
  OAuth exchanges and user-token workflows remain intentionally unexercised.
- PR preparation (September 15): fetched both remotes; upstream `main` remains
  `2866c9066d36c1f4de978e21041f76a7395c1d24`, with no additions to the 114-row
  intake. Origin `main` is `e465031`; semantic integration does not merge Git
  ancestry. Docker restart retained customer/invoice data. An application-created
  backup restored into isolated database `slowbooks_pr_restore_20260915`, with
  matching migration/account/customer/invoice/line/user counts and the $125
  invoice. Three real receipt OCR fixtures passed in the image. Review found
  missing QB receipt warnings when controls prevent posting; the importer now
  reports unposted invoice/payment journals explicitly. The prior full-suite
  result predates this warning-only follow-up; its focused QB report gate passed
  **43 tests, one warning**. Black checked **654 files** across app/tests/scripts;
  Ruff and whitespace checks passed. Docker browser login, persisted dashboard,
  Settings, nonprofit switch/navigation and return to the unlock form on sign-out
  passed. The image predates the warning-only change, which was tested locally.
  Final accumulated-diff review,
  native/live acceptance and contributor-term decisions remain open.
- Real Docker install/runtime smoke (September 15): isolated Compose project
  `slowbooks-validation` built both app images, started PostgreSQL 17 and the
  unprivileged app, ran every migration through `ac14bd25ce36`, seeded 57
  accounts, and reported healthy. First-run setup/login, authenticated status,
  customer creation, invoice creation/fetch, and post-write `/health` all
  passed against the live container. The stack was stopped without touching
  existing containers; project-scoped synthetic volumes remain for a repeat
  run. No external providers or real user data were used.
- Definitive full Python-suite run (September 15): after the focused fixes,
  **4,564 passed, 31 skipped, zero failed, two warnings** in 14m31s. The
  4,595-test graph completed successfully; skips are the documented PostgreSQL,
  OCR-binary and deliberate public-route gates. Frontend remains separately
  green at **29 passed**. This closes the full-suite execution gate for the
  current tree; native artifacts, live providers and deployment capacity remain
  separate release gates.
- Full Python-suite baseline and triage (September 15): the complete run of
  **4,595 tests** finished in 15m37s with **4,550 passed, 30 skipped, 15
  failed, and 2 warnings**. The failures split into stale expectations for the
  local migration head/table count and intentional strict control-account
  protection, one brittle auth-exemption parser, and three real importer
  regressions. The migration/doc/auth expectations and strict credit behavior
  are now aligned; IIF and QB report imports retain records with an unposted
  warning when the chart lacks required controls, and late-fee missing-control
  errors translate to HTTP 400. The affected-cluster run reported **148 passed,
  four skipped, three failed**; after the remaining IIF fixes, a separate
  four-test rerun passed. These overlapping runs are not a single 152-test gate.
  The definitive full-suite result above supersedes this failed baseline.
- Upstream-intake scope note (September 15): future `main` updates are treated
  as a defect/behavior queue, not as a requirement to reproduce every commit's
  ancestry. Apply the smallest compatible fix, add one or two focused regression
  tests where useful, and run the directly relevant gate. Reserve deeper commit
  reconstruction for real migration, security or conflict risk. The existing
  114-row ledger remains provenance for this large intake; it is not the default
  process for later updates.
- Whole-tree collection/frontend closeout (September 15): all **4,595 Python
  tests collected** without import or collection errors; tests were not
  executed as a full suite. The complete **29-test frontend gate** initially
  exposed two sides of one AI Settings regression: Custom's required model ID
  was unbounded/hidden on first selection, and the intro no longer named the
  self-hosted gateway or custom endpoint. The prior 255-character contract,
  generic-provider initial state, visibility synchronization and provider text
  are restored. Frontend rerun: **29 passed**; AI provider/config fallback:
  **137 passed, one warning**. Final Black covered **714 files**; Ruff, all
  JavaScript/JSON/workflow-YAML/shell syntax and whitespace checks passed.
- Cross-cutting route/UI audit and live browser smoke (September 15): the
  accumulated audit slice first reported **590 passed, one failed**. Its sole
  failure was real: the invoice email-preview endpoint had no interface caller.
  The invoice dialog now loads the saved template, debounces the operator note,
  and renders returned HTML only through a sandboxed `srcdoc` iframe. The
  repaired wiring/document gate passed **49 tests, one warning**. A disposable
  seeded-server browser smoke then visibly passed sign-in, dashboard balances,
  ordinary-invoice preview and live note refresh inside that sandbox, plus the
  unified Banking page. The automation bridge timed out on the subsequent
  Settings mode toggle, so that interaction is not claimed; the exact nonprofit
  terminology/Settings/sign-out/preview fallback gate passed **58 tests, one
  warning** instead. No email was sent and the scratch server was stopped.
- Seeded live vocabulary walk (September 15): disposable migrated SQLite,
  57-account chart, two invoices (pledge and ordinary), estimate and bill.
  The corrected walker covered every harvested real ID, captured **2,862
  business and 2,853 nonprofit strings**, and reported **0 source-backed code
  leaks and 0 unclassified dynamic results**; three document-face occurrences
  were intentional. Classification regressions: **26 passed, one warning**.
- Disposable PostgreSQL 17 closeout (September 15): migration/model parity,
  concurrent journals/audit chains and bank row locks passed (**21 passed, five
  intentional SQLite-variant skips**). A new half-upgrade fixture exposed the
  vendor-credit enum collision and parent/child drop ordering. The migration
  now reuses an existing compatible enum; repair verifies the full dependent
  closure is pending-created and empty, drops child-first without `CASCADE`,
  and refuses before any drop when a child has data. Recovery and refusal both
  passed on real PostgreSQL (**2 passed**); local SQLite/static repair gate:
  **17 passed, one PostgreSQL test deselected**.
- Vocabulary/document composition: **82 passed, one warning** (33.05s).
  HTTP/control/AI wording and document-face posting references pass alongside
  email and vendor-credit regressions. Audit walker incorporated without a
  default password; the live seeded walk above supersedes its earlier deferral.
- Windows CI/macOS HarfBuzz follow-up: Windows 3.13 lane added with named tests,
  timeout and skip budget while preserving Linux PostgreSQL/frontend coverage;
  Pillow font modules are excluded before macOS bundle analysis. **35 passed,
  one warning** (2.84s); YAML, Black, Ruff and whitespace checks passed. Hosted
  Windows/native macOS execution remains open.
- Vendor credits and schema repair: **44 passed, one warning** (96.39s).
  Vendor posting/application/void/aging and the local migration join pass;
  SQLite repair distinguishes leaked tables from legitimate merge-parent tables
  using a disposable baseline and refuses data-bearing blockers. The real
  PostgreSQL recovery/refusal gate above supersedes its earlier deferral;
  the definitive full-suite result above supersedes that earlier deferral.
- Email template preview/send integration: **67 passed, one warning** (13.40s).
  Shared sandbox rendering, saved-template use, escaping, secret redaction,
  request-local blank reporting and conditional values pass. The seeded browser
  smoke above covers the invoice dialog's rendered preview; live SMTP remains
  open.
- Test-lifecycle/encoding follow-up: guarded cleanup of anyio-retained closed
  loops plus explicit UTF-8 source reads, **57 passed, one warning** (22.04s).
  Black, Ruff and whitespace checks passed; full-suite memory measurement waits.
- Windows missing-WebView2/browser fallback and opt-in timer lifecycle:
  **49 passed, one warning** (15.32s). Existing LAN TLS and child cleanup were
  retained. Black, Ruff and whitespace checks passed. DLL/registry behavior is
  simulated; native Windows and full-suite acceptance remain open.
- Bank of America CSV/import-dialog integration: **50 passed, one warning**
  (11.15s), plus **29 frontend tests passed**. Upstream fixture matches byte-for-
  byte; bounded header search, balance-row exclusion, finite signed amounts,
  re-import dedup and queue-to-ledger signs tested. Import buttons show activity
  and recover after failure without depending on focus. No live bank connection,
  native browser acceptance, full retest, commit, push or PR.
- Consecutive integration pass: macOS timestamp retries and commit identity
  (**27 passed**, 0.59s), control-account documentation adapted to later cleanup,
  and a reusable audit-hook session factory with fresh per-test databases.
  Startup/lifespan execution deliberately retained. Combined fixture/audit/
  controls/banking/desktop gate: **101 passed** (101.79s); each gate had one
  warning. Black **639 files**, Ruff and whitespace checks passed. No actual
  signing/build, full retest, memory benchmark, commit, push or PR.
- macOS release diagnostics: checked failures print/preserve stdout and stderr;
  command identity redaction retained. Mocked release/packaging gate: **20 passed,
  one warning** (0.53s); targeted Black, Ruff and whitespace checks passed.
  No signing/notarization/build commands ran. Closes the `a38cca2` implementation
  remainder; later release-helper changes and native acceptance remain separate.
- Windows version metadata: generator, executable wiring and pre-signing
  workflow check integrated without changing the app version. **15 passed, one
  warning** (1.72s), covering generated syntax/content, wiring, launcher and
  macOS packaging regressions. Targeted Black, Ruff and whitespace checks passed.
  No Windows build, workflow run, signing or native artifact inspection.
- Headless launcher follow-up: selection persistence disabled for headless/smoke
  launches, preserved for windowed use. Existing LAN TLS, health probes and
  child cleanup retained and tested. Parser/image errors now omit library text.
  Gates: **49 passed, two native-tool skips, one warning** (23.41s), and AI
  transport/security **64 passed, one warning** (0.30s). Windows executable
  version metadata and native artifact acceptance remain pending. No full
  retest, commit, push, merge or PR.
- Native PDF raster integration: Windows/macOS renderers with Poppler fallback,
  corrected WinRT call, ImageIO probe, status/Settings display and Windows
  dependency added. Ordinary library ValueErrors and launch failures are
  sanitized; authored renderer errors use an explicit marker. OCR/intake/
  storage/conversion/subprocess gate: **146 passed, one warning** (28.74s),
  including real Poppler rendering and simulated native bridges. Black **633
  files**, Ruff, JS syntax and whitespace checks passed. Existing validation
  and cleanup guards retained; native installed-artifact acceptance and related
  release/launcher changes remain open. No full retest, commit, push or PR.
- Batch claims, lock order and cash flow: **80 passed, one warning** (37.37s).
  Batch workers claim current statement rows; busy ledger rows are retried,
  avoiding the matching/void lock-order wait. Approved cash-flow changes now
  exclude non-cash activity, internal transfers and opening balances, using
  bank-kind accounts without requiring feeds. Real PostgreSQL 17 locking plus
  accounting/audit concurrency gate: **13 passed, five SQLite-only skips, one
  warning** (23.15s). Synthetic disposable container/database removed afterward.
  Black **631 files**, Ruff and whitespace checks passed. PostgreSQL migration,
  other banking races, browser acceptance and full validation remain open.
- Statement matching follow-up: automatic matching rechecks stale candidates
  using manual-match validation; match/unmatch lock and refresh ledger lines.
  New regressions cover changed amounts, competing claims and reconciliation
  state changes. Focused matching/import/SimpleFIN gate: **62 passed, one
  warning** (8.22s). Black **629 files**, Ruff and whitespace checks passed.
  Batch statement claims and cross-operation lock ordering remain under review;
  no live PostgreSQL concurrency or full-suite acceptance is claimed.
- Banking navigation/void follow-up: fixed unreachable source links and the
  legacy Check Register blank-page race. Added exact-document routes and used
  journal views for standalone postings. Gates: **32 passed** (5.59s), **27
  frontend checks passed**. All void paths now lock/refresh ledger lines before
  rejecting reconciled entries; route-lock and stale-cache regressions plus
  banking/reconciliation checks: **33 passed** (26.92s). Each Python gate had
  one warning. Black **628 files**, Ruff, JS syntax and whitespace checks passed.
  Live PostgreSQL concurrency, browser acceptance and full validation remain open.
- Banking runtime integration is now present, not merely under review: GL
  register/balances, posting/transfers, statement review and reconciliation.
  Earlier isolation/locking/totals/import regressions were adapted to the new
  contracts. Gates: **25 passed** (10.68s), then **98 passed, four skipped**
  (29.04s), each with one warning. SQLite migration upgrade/downgrade reached
  the local banking join; PostgreSQL concurrency remains unverified. Manual
  matching of voided entries was reproduced and guarded; follow-up banking/
  import/migration gate: **34 passed, one warning** (14.90s). Remaining
  concurrency/navigation work is tracked in the upstream ledger.
  No full-suite run, live migration, commit, push, merge or PR.
- Sidebar/encoding follow-up: update notice/version moved into the sidebar
  header; available upstream UTF-8 reads integrated without changing session-key
  persistence safeguards. Gates: **53 passed** (11.50s) and **31 passed** (5.83s),
  each with one warning. Added executable account-controller regressions for
  rendered handlers, delete cancel/refusal/success and reactivation: **20 frontend
  tests passed**. Black **609 files**, Ruff and whitespace checks passed. Missing
  version-resource/OCR fixtures remain with their feature groups in the ledger.
- Attachment/UI follow-up: **36 passed, one warning** (9.32s). Legacy Windows
  attachment paths now download/delete across platforms; new paths use POSIX
  separators. Unique upload names, traversal checks and absolute-path rejection
  are preserved. Existing correct route order is covered by HTTP and mounted-
  route checks. Added hidden-class, Quick Entry and link/success/footer contrast
  fixes, including the local footer-link override. Ruff, JS syntax and whitespace
  checks passed. Raster/platform fixture work remains tracked separately; no
  whole-browser accessibility certification or full-suite rerun claimed.
- Import/clipboard/PDF integration: real Wave export headers and filenames
  preserved nonzero journals (**17 parser/source tests**, one warning); shared
  clipboard behavior passed **15 frontend tests**. PDF logos now reach every
  supported document header. Upgraded requirement and local venv to WeasyPrint
  **70.0**, integrated lazy data-only fetcher and packaging support, and retained
  local upload-path/currency safeguards. Final PDF/report/packaging/API gate:
  **85 passed, one warning** (14.71s). Black **607 files**, Ruff and whitespace
  checks passed. Native-stack-blocked import tested in an isolated subprocess;
  full missing-stack suite and native artifact builds remain deferred. No full
  suite, merge, commit, push or PR. README unchanged.
- Control-account and account/email UI integration: **125 passed** in the
  control/export/regression gate; **70 passed, two on-demand-account skips**
  in the account-cleanup/markup gate; **26 passed** in the email/helper gate.
  Each Python gate reported one warning; **10 frontend checks** passed.
  Missing posting accounts now fail loudly, ordinary unused seeded accounts
  can be deleted, and inactive accounts remain reachable. Invoice messages
  reach escaped template/fallback bodies without weakening strict validation.
  Rationale, follow-up fixes and test adaptations are in the upstream ledger.
  No full-suite rerun, live migration, merge, commit, push or PR. README unchanged.
- Error-handling rationale follow-up: integrated typed donor ineligibility,
  QB-report sanitization, isolated widget failures, sanitized invoice EmailLog
  failures and test-email errors. Gate: **98 passed, one warning** (44.39s).
  Adopted explicit authored-error markers in accounting, job costing, time
  entries and import parsers, preserving local numeric and account safeguards.
  Two old tests assumed arbitrary ValueError text was public; expanded them
  to verify safe authored text versus sanitized unexpected errors. Final gate:
  **53 passed, one warning** (5.95s). Black (597 files), Ruff and whitespace
  checks passed. Rationale/adaptations recorded in the upstream ledger;
  control-account integration remains pending. No full suite, merge, commit,
  push or PR. README unchanged; final documentation polish remains deferred.
- Local integration follow-up: QBO callback exemption and QBO/IIF route/row
  error sanitization integrated while preserving local import safeguards.
  Callback tests cover no-cookie success, missing/incorrect/replayed state,
  protected neighboring routes and sanitized provider ValueErrors. The shared
  helper never returns database-driver text, including the first constraint
  line. Focused callback/auth selection: **49 passed, 515 deselected, one
  warning** (11.99 seconds). Combined import/export/OAuth/helper gate:
  **169 passed, one warning** (23.02 seconds). Black (597 files), Ruff and
  whitespace checks passed. Provider calls mocked; no full auth sweep, live
  provider acceptance or massive/full-suite run claimed. Remaining error sites
  stay partial in the upstream ledger. No merge, commit, push or PR; README
  unchanged in this batch. Final documentation polish follows large validation.
- September 14 semantic-reconciliation closeout: all **114 ledger rows** now
  have a disposition. The desktop sign-in/company-picker integration passed
  **67 tests, one warning** (55.69 seconds), with JS syntax, Ruff and formatting
  checks green; its initial nonzero shell status was only two extra EOF blank
  lines, since removed. Parked design notes were source-compared and adapted to
  the existing design directory. Nonlegal provenance cleanup is incorporated.
  License 2.0/contributor terms and their dependent splash/installer acceptance
  remain intentionally unapplied pending explicit owner acceptance. Release
  metadata and expanded README wrappers are superseded by the local Unreleased
  ledger and requested light README. The whole suite, native artifacts, live
  providers/browser flows, PostgreSQL repair and audit-walker run remained
  deferred at that checkpoint; the September 15 PostgreSQL, walker and seeded-
  browser results at the top supersede those items.
  After the two EOF-only whitespace findings were removed, the same focused gate
  repeated cleanly: **67 passed, one warning** (23.85 seconds), with JS syntax,
  Ruff and `git diff --check` green.
- September 14 full upstream reconciliation started: all **114 commits**
  (including 16 merges) are inventoried in
  [the pinned commit ledger](upstream-reconciliation-2026-09-14.md). At this
  historical checkpoint it was not a completed semantic review. Reproduced donor-template credential
  exposure with synthetic data, integrated shared redaction from `2fd6758`,
  then passed **64 tests, one warning** (50.43 seconds). Integrated PostgreSQL
  company migrate/seed initialization from `dba2839`; initialization failure
  must not register the company. Its focused gate passed **110 tests, one
  warning** (33.66 seconds), with PostgreSQL connections mocked. Black (595
  files), Ruff and whitespace checks passed. No live migration, full-suite
  rerun, merge, commit or push. Earlier 100% company coverage is historical:
  its source changed in this batch and coverage has not been remeasured.
- September 14 selective upstream intake: reviewed the newest five mainline
  updates (`fbf0c2c..2866c90`). Integrated comment-only cleanup, adapted
  contribution guidance and documented existing multi-user auth fields.
  Preserved local feature and validation claims; the then-absent sign-in
  feature and fixture were integrated in the later closeout above. No license replacement,
  sign-off or merge was performed. The decision ledger and pre-PR dependencies
  are in `docs/todo.md`; this is not a claim of full upstream synchronization.
  Focused checks: **19 Python tests passed, one warning** (8.43 seconds),
  **10 frontend tests passed**; Bash/JS syntax, Black (594 files), Ruff and
  whitespace checks passed. The deferred full suite was not rerun.
- September 14 final scoped-gap gate: **145 passed, one warning** in
  60.03 seconds; company service **245/245** and encryption **186/186**
  jointly measure **100% line coverage (431/431)**. Fault-injected filenames
  exercise the independent company-directory containment guard without
  creating files; executing the encryption module's launcher verifies usage
  and exit status without opening a database. The September 12 **14-module
  scoped remainder is now zero**, measured across the focused follow-up gates,
  not a new whole-repository run. No production changes or coverage exclusions
  were needed. Black (594 files), Ruff and whitespace checks passed.
  Full-suite validation, accumulated-diff review and separate release acceptance
  remain outstanding; nothing has been staged or committed.
  Coverage data: `/tmp/slowbooks-last-two-sep14`.
- Earlier September 13 combined remainder gate: **206 passed, one warning** in
  108.70 seconds. Benefits routes **275/275**, benefits engine **356/356**,
  job-costing service **462/462**, company service **244/245**: jointly
  **1,337/1,338 lines**. The earlier 170-line scoped remainder fell to **two
  lines**, including encryption's previously recorded launcher line. Company's
  remaining line 345 was the secondary lexical containment rejection following
  filename validation; encryption's was line 398 (`__main__` dispatch).
  The September 14 gate above supersedes this remainder count.
  No coverage exclusions or production changes were added in this batch.
  Job-costing additions verify cent conservation, date-filtered weights,
  account/amount validation, change budgets and no-posting burden cases.
  Black (594 files), Ruff and whitespace checks passed. Whole-repository
  coverage and the deferred full validation are still outstanding; this does
  not supersede separate release-acceptance requirements.
  Coverage data: `/tmp/slowbooks-core-remainder-sep13-final`.
- Benefits routes and engine now jointly measure **100% line coverage**
  (631/631): **67 tests passed, one warning**. Added contracts for effective
  dates, group/assignment exclusions, hourly/tiered calculations, flat-match
  limits, annual employer caps, unmapped expense handling, setup idempotence,
  remittance safeguards and admin conflict/update/delete behavior. Synthetic
  rate arithmetic validates implementation, not regulatory acceptance.
  Coverage data: `/tmp/slowbooks-benefits-sep13-final`.
- Earlier company-service follow-up: **104 passed, one warning**, **242/245 lines
  (99%)**. Included the existing 2.9.0 regression tests missing from the earlier
  selection, then added manifest read/reconciliation recovery, partial-create
  cleanup, date-free SQLite URLs, PostgreSQL current-company registration and
  error paths, and Windows data-directory selection. PostgreSQL connections
  were mocked and desktop writes used temporary directories. Three branches
  remained at lines 136, 345 and 445; the combined gate above supersedes this count.
  Coverage data: `/tmp/slowbooks-company-sep13b`.
- Inventory service now measures **100% line coverage** (128/128). Its 22-test
  focused gate covers nontracked/nonpositive no-ops, weighted and zero-balance
  cost changes, receipt/COGS postings, account fallback, adjustments, historical
  reversal cost and legacy fallback behavior.
- Earlier September 13 measured-slice status: follow-up gates reduced the September 12
  core remainder from **364 to 170 lines**. The remaining measured lines were
  company service 68, job-costing service 40, benefits routes 34, benefits
  engine 27, and encryption's one-line module launcher. This is still a scoped
  measurement rather than whole-repository coverage; the combined gate above
  supersedes this remainder count.
- Local-tax engine now measures **100% line coverage** (202/202). Its 40-test
  focused gate covers table validation/loading failures, bracket boundaries,
  every locality-basis calculation, employer percentage/flat levies, unknown
  codes and payroll integration.
- Sage migration adapter now measures **100% line coverage** (73/73). Its
  13-test focused gate covers blank/unmapped chart rows, absent charts,
  unresolved account IDs, malformed GL/TB values, valid balance aggregation,
  missing-bundle handling and end-to-end imports.
- GnuCash and Zoho migration adapters now jointly measure **100% line
  coverage** (126/126). Their 14-test focused gate covers blank, structural,
  unmapped and malformed rows; signed values; valid/invalid trial balances;
  missing-bundle wrappers and end-to-end imports.
- MYOB migration adapter now measures **100% line coverage** (92/92). Its
  14-test focused gate covers classification and absent-chart fallbacks,
  blank/unmapped COA rows, malformed GL/TB values, duplicate account names,
  code-only resolution, report preambles and end-to-end imports.
- Xero migration adapter now measures **100% line coverage** (64/64). Its
  13-test focused gate covers classification, blank/unmapped COA rows, blank or
  malformed journal rows, invalid trial-balance cells, dry-run rejection,
  imports and opening-balance behavior.
- Wave migration adapter now measures **100% line coverage** (81/81). Its
  12-test focused gate covers keyword account mapping, signed amounts, blank
  and malformed COA/GL rows, report headings/subtotals, invalid trial-balance
  cells and end-to-end import behavior.
- September 13 encryption and migration-common follow-up: encryption runtime
  paths now measure **185/186 lines (99%)** with 36 focused tests; the sole
  uncovered line is the module's `__main__` dispatch. Tests cover empty and
  corrupt values, date/enum conversion, raw and typed key rotation failures,
  successful raw rewrapping, CLI results and session cleanup. Shared migration
  helpers now measure **100% line coverage** (168/168); 33 tests cover invalid
  cells, classifier/preamble fallbacks, duplicate/missing accounts, account-code
  collisions, opening-balance noise, negative-side normalization and empty
  journals. Both gates passed with one warning; Black, Ruff and whitespace
  checks passed. Coverage data: `/tmp/slowbooks-encryption-sep13c` and
  `/tmp/slowbooks-migration-common-sep13b`.
- September 12 remaining-slice measurement: **241 passed, one warning** in
  130.58 seconds across 23 existing test files. Selected encryption/settings,
  company/desktop, benefits, job costing, reports, six migration formats,
  local tax, inventory and IIF round-trip tests; no full-suite rerun.
  The 14 core target modules measured **2,094/2,458 lines (85.2%)**, leaving
  364 uncovered: company service 68, encryption 48, job costing 40, benefits
  routes 34, benefits engine 27, Sage 23, GnuCash/Zoho 21 each, inventory 20,
  local-tax engine 18, migration common 14, MYOB/Xero 11 each and Wave 8.
  These are this batch's coverage gaps, not proof of defects or an overall
  completion percentage. Report-schema and payables-tax coverage requires
  separate test selection. Historical line evidence was used only for triage.
  Coverage data: `/tmp/slowbooks-remaining-slice-20260912`.
- September 12 backup/restore follow-up: **57 tests passed, one warning**;
  service coverage is **133/134 lines (99%)**. Added failure cases for tool
  timeouts/missing binaries/nonzero exits, invalid filenames, SQLite partial
  snapshot cleanup, non-file databases and corrupt-restore data preservation.
  PostgreSQL backup failures now return a generic error and log tool details.
  The remaining uncovered line is the secondary lexical containment rejection
  after basename validation (`backup_service.py:266`); coverage is not complete.
  PostgreSQL subprocesses were mocked; SQLite used temporary databases.
  Black (581 files), Ruff and whitespace checks passed. Full-suite revalidation
  remains deferred. Coverage file: `/tmp/slowbooks-backup-sep12-verified`.
- Audit-signing helpers now measure **100% line coverage** (70/70). The
  43-test contract gate covers unsigned/unverifiable/invalid states, HMAC
  signing and rotation, payload tamper detection, duplicate-key rejection and
  strict payload shape/type validation.
- Request client-IP helper now measures **100% line coverage** (8/8). Its
  focused three-test gate covers trusted-proxy first-hop extraction, spoof-safe
  peer fallback, truncation and missing-peer handling.
- Closing-date enforcement now measures **100% line coverage** (23/23). Its
  19-test gate covers missing/invalid settings, inclusive closed-period
  rejection, encrypted password override and post-close writes across routes.
- Federal-holiday helpers now measure **100% line coverage** (47/47). The
  41-test combined gate covers statutory and Reserve calendars, observed
  weekend/cross-year dates, Sunday inauguration handling, business-day
  advancement and invalid negative counts.
- Shared IIF type-mapping helpers now measure **100% line coverage** (30/30).
  The focused boundary gate covers every account-number range, all account
  enums, all item kinds and non-numeric account-number fallback behavior.
- NACHA export now measures **100% line coverage** (203/203). Its focused
  14-test gate covers employee deposit allocation, prenotes, fixed-width
  helpers, validation failures, contractor credits/offsets, zero amounts and
  unbanked-vendor skips.
- Pay-schedule service now measures **100% line coverage** (64/64). Its
  26-test schedule/page gate covers weekly and biweekly stepping, semi-monthly
  and monthly capping across a year boundary, business-day/holiday/blackout
  shifting, cutoff derivation and CRUD/page behavior.
- Currency and FX helpers now jointly measure **100% line coverage** (110/110).
  The 39-test focused gate covers invalid rates, feed fallback success,
  rounding-drift correction and multi-currency/FX contracts.
- PTO-accrual service now measures **100% line coverage** (61/61). Its
  37-test gate covers coercion, unknown methods, negative balances, caps and
  payroll/PTO route integration.
- Overtime service now measures **100% line coverage** (54/54). Its focused
  50-test payroll/overtime gate covers empty periods, daily rules, seventh-day
  handling, zero/negative days and weekly reconciliation.
- Tipped-wage service now measures **100% line coverage** (42/42). Its
  dedicated 11-test gate covers top-up floors, FICA-tip-credit pinning,
  zero/empty coercion, and pay-run/Form 8846 integration.
- Document-numbering service now measures **100% line coverage** (40/40).
  Its focused gate covers seed/prefix/padding behavior, collision skipping,
  estimate-setting fallback and every document-number wrapper.
- Gross-up service now measures **100% line coverage** (36/36). Its focused
  50-test payroll/gross-up gate covers zero and already-sufficient bounds,
  bisection solving, implied withholding and explicit tax callables.
- Duplicate-detection service now measures **100% line coverage** (31/31).
  Its 11-test gate covers normalization, similarity, sorted matches, empty
  inputs, thresholds and customer/vendor route behavior.
- Payroll-report routes already measure **100% line coverage** (64/64); the
  focused report/register/page gate passed 11 tests with one warning and
  required no code change.
- Employee portal routes now measure **100% line coverage** (312/312). The
  consolidated focused gate covers cookie and legacy-token sessions, profile,
  bank, PTO, time and document workflows, access-audit failures, favicon
  containment, logout and signature consent/integrity boundaries.
- The fixed-assets service now measures **100% line coverage** (154/154). Its
  13-test gate covers depreciation methods/caps, mapping validation, numbering
  collisions, disposal guards and CSV validation plus rollback behavior.
- The payment-provider package now jointly measures **100% line coverage**
  (287/287 across registry, PayPal, Square and Stripe). The consolidated
  40-test mocked gate passed; this remains distinct from live-processor
  acceptance.
- Financial-report routes now measure **100% line coverage** (244/244). The
  expanded focused gate covers general-ledger source links, trial balance,
  cash-flow sections, COGS class aggregation, default-date class/job reports,
  balance-sheet PDF rows and nonprofit statement-pack dispatch.
- The Square provider adapter now measures **100% line coverage** (92/92).
  Its eight-test mocked gate covers link construction/failures, signed webhook
  rejection/filtering/completion and every polling state, including Square's
  open-but-paid order shape; it is not live-processor acceptance.
- The Stripe provider adapter now measures **100% line coverage** (45/45).
  Its 28-test mocked gate covers configuration, checkout construction, webhook
  validation/filtering and paid/cancelled/pending polling states; it is not
  live-processor acceptance.
- The PayPal provider adapter now measures **100% line coverage** (123/123).
  Its 26-test mocked gate covers auth/order failures, invalid webhook payloads,
  approval and capture extraction, pending/void/unknown polling and cache-safe
  provider flows; it is not live-processor acceptance.
- The CSV bank-import service now measures **100% line coverage** (170/170).
  Its 44-test gate covers every supported format, date fallbacks, malformed or
  missing rows, mirror-transfer suppression, BOM/header handling, unknown
  input, deduplication and bank-rule parity.
- The blind-index service now measures **100% line coverage** (108/108). Its
  43-test gate covers index recovery, stale registrations, CLI usage and exit
  paths, dry-run reporting/session cleanup and canonical module delegation.
- Settings-secret crypto now measures **100% line coverage** (63/63). Its
  13-test gate covers environment/file/atomic and fallback key lifecycle,
  persistence refusal, encryption migration behavior, tampering and display
  masking.
- The OFX/QFX import service now measures **100% line coverage** (51/51).
  Three focused cases cover native and fallback parsing, incomplete records,
  FITID deduplication, persisted import metadata and conditional rule dispatch.
- The garnishment service now measures **100% line coverage** (132/132). Its
  21-test gate covers coercion, CCPA protected earnings, shared child-support
  rounding and arrears caps, levy/bankruptcy limits, student-loan aggregation,
  creditor safeguards and the final no-over-withholding invariant.
- Payroll-export routes now measure **100% line coverage** (53/53). The
  16-test focused gate covers PDF pay-stub context and download headers plus
  ACH missing/unprocessed runs, company/date defaults, service-error
  translation and successful attachment responses.
- OCR routes and service now measure **100% line coverage** (187/187 and
  538/538). The consolidated OCR gate passed **198 tests**, skipped seven
  absent native Tesseract/Poppler checks, and issued one warning. New boundary
  coverage covers template overrides, PDF/image serving, bill attachment,
  region error translation, symlink containment, corrupt intake sidecars and
  failed intake cleanup. The native skips remain separate acceptance work.
- AI provider service now measures **100% line coverage** (396/396). The
  combined mocked provider/DNS/transport gate passed **149 tests**, one warning,
  across all adapters, SSRF resolution, request/response formats, tool loops,
  credential redaction and malformed payloads. This is not live-provider
  acceptance.
- Item and email-template routes now jointly measure **100% line coverage**
  (131/131). Focused CRUD/filter/ledger/adjustment/low-stock and template
  default-seeding/duplicate/missing cases pass; an added two-contract gate
  passed after correcting a test-only Decimal display assertion.
- Schedule-C and payroll-tax routes now jointly measure **100% line coverage**
  (140/140). The focused selection passed 56 pre-existing cases before one
  test-only call-count correction; the corrected two-contract gate passes.
  Coverage includes mapping upserts/account validation, default/explicit date
  CSVs, payroll form dispatch/PDFs, quarter checks and 1099 error translation.
- Unified search routes now measure **100% line coverage** (33/33), with all
  six supported entity categories, empty results and minimum query length
  covered in one isolated integration case.
- Credit-card charge, deposit and check routes now jointly measure **100% line
  coverage** (123/123). Twenty-two targeted accounting/closing cases pass.
  Partial deposits now report the source payment's remaining amount instead of
  its full original debit; charge controls, allocation detail and both customer/
  vendor check paths are pinned.
- Fixed-asset routes now measure **100% line coverage** (136/136). Nine
  focused cases pass default-type seeding, type/asset CRUD and filters,
  depreciation/disposal accounting, reconciliation, missing resources and
  UTF-8/Latin-1 CSV intake.
- PTO routes and schemas now measure **100% line coverage** (258/258). The
  31-test gate passes policy CRUD/validation, enrollment uniqueness, accrual
  caps and liability error rollback, revaluation, request filters/decisions/
  balance drawdown and year-end carryover.
- Onboarding routes and HR schemas now measure **100% line coverage**
  (139/139). Seventeen focused cases pass first-access/default seeding, custom
  task validation and lifecycle timestamps, repeat completion, missing records,
  state-report data and mocked PDF generation/error translation.
- Provider-payment routes now measure **100% line coverage** (98/98). The
  27-test gate passes provider enablement/configuration, invoice eligibility,
  checkout persistence, ignored/invalid/paid webhook paths, external-ID lookup,
  polling/idempotent recording and payment-link token minting. Provider calls
  are mocked; this is not live processor acceptance.
- Purchase-order routes and schemas now measure **100% line coverage**
  (230/230). The 29-test gate passes CRUD/filtering, update validation,
  numbering collision/exhaustion, account precedence, tax and inventory-aware
  conversion. Tax-rate-only edits now recompute totals; unknown replacement
  vendors/statuses are rejected before persistence.
- Time-entry routes now measure **100% line coverage** (193/193). The 52-test
  completion gate passes filters, daily-hour edits, pay-run locks, workflow
  transitions, single/batch job posting and error translation, overtime
  classification and pay-period summaries. The wider endpoint selection passed
  **118 tests**, one warning.
- Employee routes now measure **100% line coverage** (288/288). The focused
  completion gate passed **121 tests**, one warning, covering CRUD/privacy,
  portal and E-Verify boundaries, YTD, encrypted direct-deposit validation,
  document-vault limits/storage errors and scheduled offboarding. The wider
  employee-referencing selection also passed **717 tests**, one warning.
- Core banking routes and schemas now measure **100% line coverage** (193/193).
  Five focused cases pass across account/transaction CRUD and filters,
  reconciliation ownership/totals/state transitions, error paths and asset/
  liability check-register arithmetic. Decimal totals avoid float drift.
- Recurring routes and schemas now measure **100% line coverage** (171/171).
  Eighteen focused cases pass, including CRUD, filtering, generation, line-tax
  behavior and validation. Unsupported/null frequencies and end dates before
  the immutable start date now return 422 instead of reaching persistence.
- Job-costing routes now measure **100% line coverage** (264/264). Seven
  boundary cases cover cost-type/equipment CRUD, missing references, fallback
  account caching, filters, service-error translation and in-use deletion;
  the pre-existing 43-test job/class/cost gate also passed (one warning).
- Bank-import routes now measure **100% line coverage** (53/53). Eight mocked
  upload cases cover UTF-8 and Latin-1 OFX/CSV decode paths, preview shaping,
  parser errors, missing bank accounts and importer dispatch. No network or
  customer bank data was used and no production change was required.
- Invoice lifecycle and credit-memo routes now each measure **100% line
  coverage** (204/204 and 164/164). Invoice collision/item branches passed a
  14-test completion gate; credit CRUD/post/apply/void/collision and inventory
  branches passed nine. The broader invoice selection passed **1,416 tests**
  with 56 warnings. This is targeted selection, not a full-suite rerun.
- Bill due-on-receipt terms reproduced a 30-day drift and now use the shared
  terms parser. The related bill/accounting gate passed **68 tests**, one
  warning. CRUD/account precedence/tax/void coverage then passed six tests;
  inventory and default-account branches passed 13 and five-test gates.
  Bill routes now measure **100% line coverage** (146/146).
- Credit memo completion passed nine targeted route/inventory cases and now
  measures **100% line coverage** (164/164). Original postings also inherit
  the memo's job so their dimension-specific reversal nets correctly.
- Estimate follow-up reached **100% route line coverage** (191/191). Regressions
  fixed tax-rate-only edits leaving stale totals, due-on-receipt conversion
  drift and missing job/cost tags in converted journal lines. The focused
  estimate route gate passed 11 tests; conversion branches passed two more;
  broader related gates passed **88** and **53** tests, one warning each.
- Credit applications now reject zero/negative amounts and cross-customer
  invoices before mutation; original-invoice references must exist and match
  the memo customer. The first three regressions all failed before the fix;
  the five-case expanded boundary set and a **40-test** credit/pledge/rounding/
  closing/inventory gate pass with one warning. Coverage completion continues.
- Duplication after late fees: taxed and untaxed regressions reproduced
  unbalanced-journal failures because the copied header included fees absent
  from its lines. A fresh duplicate now totals the copied stored sale lines
  plus stored tax, excluding separately assessed fees and leaving the source
  unchanged. **69 targeted invoice/fee/tax/inventory/donor tests passed**, one
  warning. Ruff, Black (532 files including scripts) and whitespace checks
  pass. No full-suite rerun or new overall coverage claim.
- Late-fee lifecycle follow-up reproduced missing job attribution and a void
  leaving fee A/R and income behind. Fees now inherit the invoice job; invoice
  voids reverse separate fee postings on their own dates with their original
  tags. **66 targeted invoice/inventory/job/class/pledge tests passed**, one
  warning; the subsequent **11-test fee gate passed**, one warning, including
  posting-date preservation, repeat-void rejection and rollback of the first
  reversal when a later fee-date check rejects the operation. Ruff, Black
  (531 files including scripts) and whitespace checks pass. No full-suite rerun.
- Invoice reversal follow-up reproduced balanced-overall but nonzero-by-tag
  reversals. Voiding now uses the shared `reversing_lines` helper, preserving
  historical job/class, cost code/type and function. **65 targeted invoice,
  inventory and job/class tests passed**, one warning. A further regression
  caught duplicated cost codes missing from journal lines despite being copied
  to document lines; fixed propagation passed the subsequent **30-test invoice,
  job-costing and line-tax gate**, one warning. Ruff, Black (530 files including
  scripts) and whitespace checks pass. Full-suite revalidation remains stopped.
- Invoice duplication follow-up reproduced lost job attribution, line-level
  job/class overrides, cost codes/tax-exempt flags and an incorrect extra
  30 days for due-on-receipt terms. Duplication now preserves these fields,
  propagates attribution to the journal, and uses the shared terms parser.
  **85 invoice/inventory/job/class/pledge tests passed**, six warnings, before
  the final cost-code/tax-flag addition; the subsequent **40-test invoice,
  job-costing and line-tax gate passed**, one warning. Ten new cases cover
  these contracts plus missing IDs, due-date fallbacks and send/void guards.
  Ruff, Black (529 files including scripts) and whitespace checks pass.
  Only targeted tests were run; overall coverage has not been remeasured.
- Full revalidation was stopped at the user's request: continue only the
  remaining coverage gaps with targeted tests. The interrupted run reported
  **631 passed, 3 skipped, 16 warnings** before KeyboardInterrupt; it is not
  a completed checkpoint and its coverage must not replace the frozen baseline.
  Runner/log prefix: `/tmp/slowbooks-final-revalidation-20260908c`. Post-test
  fingerprint and frontend gates were not reached. Do not restart the full
  suite during this gap-closing pass.
- Invoice late-fee contracts: **26 tests passed**, one warning. Added checks
  for sent/partial versus draft/void/paid eligibility, the exact grace boundary,
  tiny rounded fees, disabled/missing-account rejection, balanced postings,
  consistent totals and repeat-run safety. No production changes in this batch.
- PDF-service follow-up: four amount-wording regressions reproduced fractional
  cent carry, half-up rounding and negative-cent failures. The service now uses
  the canonical Decimal money helper. **91 tests passed**, five warnings; a
  subsequent resource-boundary gate passed **25 tests**, one warning. Combined
  focused coverage reaches **100%** (126/126 service lines), including external
  URL rejection, logo containment/read failures and shared-renderer dispatch.
  Dispatch/resource tests use mocks; this is not visual or PDF/UA certification.
  Ruff, Black (520 files) and whitespace checks pass. Coverage data is at
  `/tmp/slowbooks-pdf-boundaries-final-20260908`; overall coverage is not rerun.
- Benefit-rate deletion: four regressions reproduced broken middle intervals
  and erased expiry dates. The fix reconnects only an adjacent predecessor.
  Seven regression cases also verify intentional gaps remain unchanged.
- Group-code duplicates reproduced database integrity failures on create and
  replacement. They now return 409 before replacing existing codes. The combined
  payroll/benefits gate passed **139 tests**, one warning. A subsequent three-test
  group gate also passed, covering replacement responses, invalid-code/member
  rollback, duplicate names and membership cleanup on deletion. Ruff, Black
  (518 files) and whitespace checks pass. Full-suite revalidation remains due.
- AI provider/transport follow-up initially passed **146 tests**, one warning;
  the later completion gate above supersedes its 98% measurement.
- QB report import follow-up: **65 tests passed**, one warning; module line
  coverage reached **100%**. Checks cover
  malformed blocks, independent rollback with later valid imports, numbering
  collisions, missing chart/mapped-item fallbacks and report detection.
- IIF export follow-up: **32 tests passed**, one warning. Coverage reached
  **100%** across estimate balancing, mapped/fallback accounts, tax and zero
  lines, unapplied payments, field sanitation and date-filtered exports.
- Further post-checkpoint work: OCR metadata now requires matching intake ID
  and stored filename. Seven regressions reproduced invalid field handling and
  cross-receipt deletion by mismatched expiry metadata; the fixed OCR gate
  passed **184 tests**, skipped four native-binary cases, with one warning.
- CSV export and bank-rule coverage: **70 tests passed** (three warnings),
  checking formula escaping, inactive-record filtering, exact values, matching
  priority, manual-category preservation and repeat-apply idempotence. A later
  **53-test export gate passed** (three warnings) with date-boundary checks;
  CSV export and bank-rule routes now each measure **100%** line coverage.
- Budget regressions reproduced duplicate keys failing within one bulk upload
  and invalid months being persisted. Bulk upserts now track pending rows,
  and request months are constrained to 1–12. **76 budget/report/accounting
  tests passed**, five warnings; budget routes now measure **100%** line
  coverage. These changes are newer than the frozen full-suite checkpoint.
- OCR conversion follow-up: 15 added tests verify real Pillow preprocessing
  dimensions/binary pixels, corrupt-image fallback, first-page-only converter
  arguments, page-count fallback, bounded errors and temporary-file cleanup.
  Converter subprocesses are stubbed; this is not native PDF/OCR acceptance.
  Combined OCR gate: **177 passed, 4 skipped, one warning**, plus SQLite teardown
  warnings. OCR service line coverage is now **93%** (500/535 lines) in that
  focused run; 35 lines remain uncovered. No production changes in this batch.
  Ruff, Black (516 files) and whitespace checks pass.
- Post-checkpoint OCR work: 17 new intake cases reproduced 14 failures from
  malformed metadata and aware/naive timestamp comparisons. A shared timestamp
  validator now rejects invalid shapes and normalizes timezone-aware dates.
  The broader OCR gate passed **162 tests**, skipped four missing-binary cases,
  and reported one warning (plus SQLite teardown resource warnings). Tests also
  verify oldest-first byte/file-cap eviction and missing-file handling. Black
  (515 files), Ruff and whitespace checks pass. This changes code after the
  89.96% frozen checkpoint below and requires another final full-suite run.
- Verified at 100% module line coverage: accounting, CSV import, QBO common/
  import/export/service/routes, AI query tools and analysis actions, analytics
  routes, NACHA export, paystub presentation, FX, email, authentication and
  document audit, IIF import/export, CSV export, bank-rule routes and budget
  routes, QB report import, PDF service and AI provider service.
- Verified near-complete: native OCR adapters and receivables routes, both 99%.
- AI response regressions previously reproduced eight malformed-response
  failures. Fixed non-object envelopes, non-string text and malformed nested
  tool calls; the final provider-service gate above now closes the remaining
  DNS, URL and wire-format paths too.
- OCR subprocess boundary checks added: controlled timeout/missing-binary/exit
  failures, language arguments, empty output, malformed TSV rows and paragraph
  grouping. Later OCR completion coverage above supersedes the earlier
  incomplete parser measurement.
  Historical frozen full-suite missing-line counts: AI provider service 108, OCR service
  101, benefits routes 59, PDF service 58, invoice lifecycle 51, job-costing
  routes 49, credit memos/budgets 47 each, QB report import/IIF export/estimates
  46 each. Follow-up gates above supersede these counts for completed modules;
  they are not current missing-line totals or defect-severity rankings.
- Frozen full-suite validation passed: **3,634 passed, 10 skipped, 96 warnings**
  in 1,207.91 seconds. Coverage is **89.96%** (24,325/27,039 executable lines;
  2,714 missing), up from 82.35%. Log:
  `/tmp/slowbooks-coverage-full-20260908b.log`; XML: the matching `.xml` path.
  The runner then stopped because host Node was absent; frontend save/refresh
  tests passed separately (10/10) in cached `node:22-alpine`, network disabled,
  repository mounted read-only. Source fingerprint independently rechecked
  after pytest and unchanged from before the run:
  `b61355e8b64cf5897a3c8f3e7eb6a99ca89c39970a70116fd319117da3274c09`.
- Skips: three deliberate authentication-exemption cases and seven native OCR
  cases without host binaries. Warnings remain; this is not warning-free.
  Black (514 Python files), Ruff and whitespace checks passed before the run.
- Before commit: complete the remaining coverage work and diff review, then
  revalidate any subsequent code changes. Nothing in this follow-up is staged
  or committed yet. This frozen checkpoint is not the final release candidate.
- Release acceptance remains separate: accessibility, native signed builds,
  live-provider/bank and payroll-data verification, sustained workload testing,
  hosted CI/CodeQL and code-owner review.

Regression tests reproduced and drove fixes for same-upload CSV duplicates,
QBO dependency mappings/false flags/historical payment double-counting, AI
income signs and expense date windows, invalid FX responses, temporary session
key cleanup, IIF payment ownership/deduplication, and invalid journal accounts
or non-finite amounts. Fixtures use synthetic records and stub external calls.

Focused module line coverage reached **100%** for CSV import; QBO common,
import, export, service and routes; AI query tools and analysis actions; NACHA
export; paystub presentation; FX; email; authentication; document audit; and IIF
import; and analytics routes. Native OCR adapters reached **99%**, without
native-hardware acceptance.
Some module totals combine overlapping focused runs; they are not independent
test counts or a new whole-suite percentage.

Latest checks: **110 auth/audit tests passed**, **8 PostgreSQL/SQLite concurrency
tests passed**, **52 auth/audit/email tests passed**, **66 IIF tests passed**, and
**28 analytics tests passed**. Analytics checks cover period boundaries, empty
books, CSV formula escaping, and exact exported values. Runs overlap and report
an existing warning; SQLite resource warnings also appeared at teardown. Ruff
and whitespace checks pass; Black passes on all 509 Python files.

The subsequent **117-test AI/analytics gate passed**, measuring analytics routes
at **100%** line coverage. It checks cache date isolation, expiry, forced refresh,
configuration invalidation, bounded provider errors, missing/corrupt credentials,
action validation, and real database tool execution behind stubbed AI calls.
The PDF route test verifies the renderer boundary and HTTP response, not PDF
layout. Corrected stale API comments about explicit key removal and cache keys.

A broader **301-test cross-service gate passed** with 17 warnings, covering QBO,
IIF, CSV, FX/multi-currency, AI tools/actions, journal input integrity, real
PostgreSQL/SQLite concurrent writes, jobs, classes, and sales receipts. In this
single run, QBO import/export, IIF import, CSV import, FX and AI query tools each
measured **100%** line coverage. This remains a focused subset, not the full suite.

Accounting service coverage subsequently reached **100%** in a **64-test passing
gate**, including closing dates, rounding, book-balance invariants and both
database concurrency backends. The previous disposable PostgreSQL container
was absent; a fresh synthetic-only container, `slowbooks-coverage-pg-20260908`,
restored the test endpoint on loopback port 5442 without touching app databases.

Statement regressions reproduced voided payments reducing customer balances
in both downloaded and batch-emailed statements. Both selectors now exclude
voided receipts while preserving the date cutoff; the two regression cases
pass and assert the exact remaining balance. Email and PDF rendering are
stubbed, with no real sends. Narrow module-targeted coverage caused a
pre-collection cryptography import error; the plain regression run passed.
Retargeting coverage to the application package passed all **21 reports,
statement, book-balance and rounding tests**, with one warning. Final Ruff,
Black (511 Python files) and whitespace checks pass.

Receivables follow-up: regression tests reproduced unescaped customer/company
names in statement and collection email HTML, and floating-point accumulation
in collection balances and income-by-customer grand totals. Email bodies now
escape names, and aggregation stays Decimal until JSON conversion. Tests also
cover 30/60/90-day cutoffs, customer filtering, aging boundaries, empty reports,
missing statements and continuation after a failed send. The combined **42-test
reports/email/accounting gate passed**, with three warnings. All sending and
rendering boundaries are synthetic; Ruff, Black (512 files) and whitespace
checks pass.

The earlier **82.35%** frozen-suite result applies only to the preceding
candidate; the current frozen checkpoint is **89.96%**, as recorded above.
Any further code changes require revalidation before commit.
Live providers, native platforms, bank acceptance and enterprise
capacity remain separate release gates, regardless of line coverage.

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
