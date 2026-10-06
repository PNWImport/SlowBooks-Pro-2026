# Upstream reconciliation — September 14, 2026

## Latest intake — September 26 (upstream 2.16.2–2.17.3)

Upstream rechecked at `90ba2b7`. The 26 commits after `a1022f8` (dated
September 22–25) are incorporated as a three-way working-tree merge: base
`a1022f8`, ours the full working tree (preserved first as
`refs/backup/pre-2.17.3-intake`, `827a902`), theirs `upstream/main`. Local
version moves to **2.18.0 unreleased**; upstream's released 2.16.2–2.17.3
CHANGELOG and What's New entries are retained verbatim.

Seventeen files conflicted. Resolutions:

- Payment ownership (#189): both sides had added the same checks; upstream's
  messages, which name the document, are kept. Our Decimal bill-balance
  comparison and payment pre-validation are kept.
- Invoice edit (#187): upstream's single posting path
  (`create_journal_entry(existing_transaction=...)`) replaces our inline
  rebuild; our account-row locking stays inside `create_journal_entry` and
  `_reverse_and_delete_journal`. Old and new accounts are now locked in two
  steps rather than one ordered call — correct, but a Postgres deadlock retry
  is marginally more likely under concurrent edits of overlapping invoices.
- Duplicate invoice: upstream's customer-based tax recompute, plus our line
  job/class/cost-code carry-over.
- OpenAI (#185): upstream's reasoning-model detection, plus our Groq
  `max_completion_tokens`. Tests reconciled (Groq keeps its parameter).
- Money widening: upstream `a9b0c1d2e3f4` and our join `ac14bd25ce36` were
  sibling heads. New join `c7d1e4a92b30` repeats the live-schema widening
  after both, so this branch's payroll columns end at Numeric(15, 2) in
  either order; remaining Numeric(12, 2) model columns widened to match.
- A semantic conflict git did not flag: upstream's invoice-edit code called
  `assert_not_reconciled(posting)`, while this branch had changed that
  function to `(db, txn)`. Every recomputing invoice edit returned 500 until
  fixed (found by the live walkthrough; 19 suite tests cover it). pyright
  shows no other new call-shape errors against the September 20 baseline.

A line-level audit confirmed that every line of ours absent from the result
was replaced deliberately (the list is in the session record); none was
dropped silently.

Also in this intake: AI model catalogue reviewed September 26 (see
`docs/ai-providers.md`). Claude 4.7+ is no longer sent a temperature (the
API refuses it with a 400); Anthropic adds `claude-opus-5-5` and
`claude-fable-5-1`, OpenAI adds `chat-latest`, xAI adds `grok-4.7`.

No commit, merge, push or PR: working-tree integration, not an ancestry claim.

## Intake — September 20 (September 21 UTC)

Upstream rechecked at `a1022f8f807faf6259d6428ced90defcbc93be95`.
All three commits after `80f2ad8` are now incorporated:

- `f7b1d49`: Wave full-export two-column headers, signed-column fallback guard,
  all-zero ledger refusal and empty-journal reporting — runtime and tests applied.
- `2348a5d`: upstream 2.16.1 release — retained in CHANGELOG/What's New,
  summarized in one README line; local version stays **2.17.0 unreleased**.
- `a1022f8`: repeated-import reference checks across all six migration sources,
  duplicate counts and synthesized opening-balance guard — runtime/tests applied.

Verification: 57 importer tests plus seven additional replay/opening-balance
tests pass; all 32 frontend tests pass. All six source formats preserve journal
counts and account balances on repeat import. Real HTTP on the rebuilt Linux
stack imported two Wave journals, previewed/skipped both on replay, refused an
unrecognized all-zero ledger and preserved the earlier paid invoice.
This verifies sequential replay of identified transactions, not concurrent
import serialization or arbitrary source-ID reuse. No schema migration.
No commit/merge/push/PR: these remain working-tree integrations, not ancestry
claims. Existing release gates and intentionally deferred owner decisions remain.

## September 20 follow-up

Incorporated the ten subsequent commits from `719735e` through `80f2ad8`:
`d52a2ea`, `42e398f`, `a2c4a25`, `e5ee680`, `95c2495`, `4fbfbd4`,
`4a201ba`, `0577823`, `b0a636b`, and `80f2ad8`. Reviewed merge effects in
the aggregate diff; existing branch fixes are preserved. Dashboard cards,
current-month boundaries, nonprofit wording, chart theme redraws and desktop
permission-denial regressions are incorporated. Windows skip ceiling follows
upstream at 78. The upstream 2.16.0 release entry is retained; this branch moves
to 2.17.0. Upstream README/release text is adapted to this branch's unreleased
status, with the dashboard additions included in `features.md`.

Focused verification: 74 Python and 32 frontend tests passed. Live PostgreSQL
HTTP evidence and the explicit browser/operation-coverage limits are recorded
at the top of `validation.md`. No commit, merge, push or PR was performed.

## Pinned scope and evidence

- Local committed HEAD: `52721f3ebba1e1ba4bd3635dee6643f6124e593b`.
- Upstream target: `2866c9066d36c1f4de978e21041f76a7395c1d24`.
- Merge base: `4ba77004a65f7a6c1bf5e47208f589e95af72b97`.
- Inventory: **114 commits**, including **16 merge commits**, in
  `git log --reverse HEAD..upstream/main` order.
- This is the complete inventory. Every row now has a semantic disposition;
  full-suite execution has passed; native/live acceptance remains separate.
- The applicability probe checked each first-parent patch with
  `git apply --check` and `git apply --check --reverse` against the dirty
  working tree before this reconciliation's runtime fixes. Both commands
  were check-only. Two reverse checks and 22 forward checks passed.
  Failure can mean changed context, dependencies or partial incorporation;
  success does not establish semantic compatibility, safety or test coverage.
- No branch merge, rebase, commit, sign-off, push or live database migration
  was performed. Migration tests use disposable SQLite databases. Uncommitted
  tests and fixes remain part of the review scope.

## Completion gates

Every non-merge change needs a final disposition (incorporated, superseded,
needed, or intentionally excluded), evidence from source comparison, and
appropriate tests. Merge commits require review of their first-parent effects
and conflict resolutions, not just counting their child commits twice.
No pending row may be treated as verified. Recheck the target SHA before PR.

Seven committed-tree textual conflict paths and the migration-head join are
tracked in [the preparation checklist](todo.md#upstream-intake-and-pr-preparation--september-14).
That preview excludes dirty changes and is not a runnable integration result.
Previously green tests and coverage remain evidence for the old tree only.

Priority review: settings/template secret redaction, safe error responses,
PDF fetch restrictions and dependency update, QBO callback authorization,
company initialization, ledger migration and reconciliation, local TLS/locking
preservation, fixture isolation, then packaging/UI/docs and release metadata.
License 2.0 and contributor-term acceptance remain an explicit owner decision;
their dependent splash/installer text is intentionally not applied yet.

### Semantic closeout

**114/114 rows are dispositioned; zero remain pending semantic review.** The
upstream tip was rechecked at `2866c90` after integration. Applicable runtime,
test, packaging and detailed-documentation effects are incorporated or locally
adapted; release-version/What's New wrappers and large README expansions are
superseded by this unreleased integration and the requested light README.

This is not the final release gate. Still open are accumulated-diff review,
native Windows/macOS artifacts, full browser
flows, live providers/SMTP and deployment-specific enterprise capacity. The
License 2.0/contributor-terms family is fully reviewed but intentionally not
applied without explicit owner legal acceptance.

The strict local production-runtime gate subsequently exercised PostgreSQL 17
with TLS, Redis shared rate-limit storage, two app workers, forced HTTPS and a
trusted forwarding proxy. It found that the documented Redis limiter URI could
not start in the image because its Python client was not declared; the
requirement and a focused regression guard were added, then the rebuilt image
started healthy with `RedisStorage`. The disposable stack was removed.

After that fix, the exact current tree completed **4,566 passed, 31 skipped,
zero failed, two warnings** in 30m27s. `pip-audit` found no known dependency
vulnerabilities, and Black, Ruff and whitespace checks passed.

Cross-cutting closeout added a route/auth/template/accessibility audit: its
first pass was **590 passed, one failed** and exposed the missing interface
caller for invoice email preview. After wiring the dialog to the saved-template
preview, debouncing its note and confining returned HTML to a sandboxed `srcdoc`
iframe, the focused repair gate passed **49 tests**. A disposable seeded browser
visibly passed sign-in, dashboard, ordinary-invoice preview/note refresh and the
unified Banking page. The automation bridge then timed out at the Settings mode
toggle; no result is claimed for that click, and a **58-test** nonprofit,
Settings, sign-out, preview and wiring fallback gate passed. Live SMTP was not
used and the scratch server was stopped.

The final non-executing whole-tree collection found **4,595 tests** with no
collection errors. The complete **29-test frontend gate** then caught a lost AI
Settings contract: the generic Custom provider's required model input was
initially hidden and lacked its 255-character browser bound, while its two
configurable endpoint choices had disappeared from the intro. Restoring the
generic-provider state, visibility synchronization, bound and provider text
produced **29 frontend passes** and **137 AI provider/config passes**. This is
focused validation, not the deferred whole-suite run.

The first executed whole-suite baseline completed in 15m37s: **4,550 passed,
30 skipped, 15 failed, two warnings**. Triage found stale local-join/table-count
expectations, a brittle QBO exemption parser, and importer/control-account
contract drift. The affected run reported **148 passed, four skipped, three
failed**; a separate four-test rerun passed after the remaining IIF fixes.
A definitive rerun then completed in 14m31s with **4,564 passed, 31
skipped, zero failed and two warnings**; the full-suite execution gate is now
closed for this tree.

A real isolated Docker Compose install also passed: the image built from this
tree, PostgreSQL 17 migrated through `ac14bd25ce36`, 57 accounts were seeded,
first-run setup/login succeeded, and a live customer→invoice create/fetch flow
returned healthy responses. The test containers/network were stopped; only
project-scoped synthetic volumes were retained for repeatability.

September 15 PR preparation fetched both remotes and reconfirmed upstream
`2866c90` unchanged (origin/main remains `e465031`). Restart persistence,
restoration into a separate PostgreSQL database, three real receipt OCR fixtures,
and browser login/Settings/nonprofit-switch/sign-out passed. Review corrected
missing QB receipt/payment posting warnings; 43 focused tests passed after that
change. The full-suite result above predates this warning-only follow-up.

A further rebuilt-image production crawl rendered all 62 static SPA routes and
loaded all 68 shell assets. It called 275 of 283 OpenAPI GET operations, excluding
only token/OAuth flows, with no 5xx response. The crawl found invalid years could
make two tax-calendar endpoints return 500; both now validate their two-year
lookback and return 422. Focused tax/auth: 42 passed; frontend/auth/system/
backend-only gate: 600 passed, four skips.

After the crawl fix, the final-tree full suite passed **4,565 tests** with 31
documented skips, zero failures and two warnings in 15m01s. This supersedes the
earlier 4,564-pass full-suite result.

Fresh PostgreSQL 17 concurrency/migration/repair validation passed 38 tests
(five deliberate SQLite variants skipped). Production Compose has a verified
fail-closed missing-value path and a synthetic resolved configuration; related
proxy/rate-limit/Docker/Kubernetes/server/PDF/subprocess checks passed 71 tests.

The final static review found no dependency vulnerabilities and no high Bandit
findings. Its six medium findings are covered by fixed-origin/allowlisted-input
guards; the supporting AI/encryption/FX/PDF/subprocess/repair suite passed 164
tests, with its two PostgreSQL skips covered by the fresh-server result above.

## Commit ledger

### Bank of America and import-dialog pass

- `fa3f5a7`, `dcd3a3f`, `55fa0f9`, `2bc2bcd`: integrated detail CSV detection,
  bounded 25-line header search, summary/balance exclusion by description,
  signed amount parsing and content-based deduplication. Imported upstream's
  sanitized export-shaped fixture; blob hash matches upstream exactly
  (`5272d158292b69eea907d02cc3e72db9ba7d3ddf`), preserving CRLF and quoting.
  Its real-export provenance is upstream evidence, not a new local bank export.
  Added non-finite-amount rejection and retained end-to-end queue-to-ledger sign
  tests. Feature/route docs updated; README/release version unchanged.
- `0a078c2` import-dialog portion plus `addcd2c`: preview now shows activity,
  disables/restores its submit button, and names Bank of America. Confirmation
  receives its actual button rather than relying on browser focus and restores
  it in finally. Added a repeated-call guard and executable success/failure tests.
  Its Windows timer portion is integrated below.
- Gates: **50 passed, one warning** (11.15s), **29 frontend tests passed**.
  Ruff and whitespace checks passed. No live bank connection, browser artifact
  acceptance, full retest, commit, push or PR.

### Windows missing-runtime and timer pass

- `1e3d596`: integrated executable guidance when WebView2 is absent and an
  offered loopback browser fallback. It starts the same default company without
  persisting selection, holds the launcher open, and always stops the child.
  Existing LAN TLS validation, health checks and cleanup remain intact.
- `0a078c2`: completed the earlier partial disposition. Windows timer resolution
  remains at the system default unless `SLOWBOOKS_TIMER_RESOLUTION_MS` is set;
  enabled requests opt out of windowless-process throttling and are matched by
  `timeEndPeriod` even when serving fails.
- Gate: **49 passed, one warning** (15.32s). Black, Ruff and whitespace checks
  passed. Registry/DLL behavior is simulated; native Windows acceptance and the
  deferred full retest remain open. README and release version unchanged.

### Test-lifecycle and encoding follow-up

- `0c114d4`: integrated guarded cleanup of closed loops retained by anyio's
  private per-run registry. It becomes a no-op if that implementation detail
  changes and leaves the existing fresh-engine/lifespan fixture contract intact.
- `33defcb`: incorporated by equivalent UTF-8 reads. The new launcher packaging
  assertion uses `encoding="utf-8"`; this branch's executable banking-dialog
  regression is a Node test and already reads `banking.js` as `utf8`.
- Gate: **57 passed, one warning** (22.04s). Black, Ruff and whitespace checks
  passed. Full-suite memory measurement remains deferred.

### Vendor-credit and safe schema-repair pass

- `9c7ebdb`: integrated vendor credits as the AP-side credit document, including
  posting, applications, voids, stock/job attribution, attachments, navigation,
  numbering, A/P aging and the matching A/R unapplied-credit correction.
  Migration `f8a9b0c1d2e3` is joined to the local payroll branch by adapting
  `ac14bd25ce36`; published parent histories were not rewritten.
- `956f17a`, `6dcca59`, `2a7bd24`: integrated the startup refusal, bounded
  repair service, source/frozen entry points and packaged script. The local
  merge graph required a stricter adaptation: SQLite builds a disposable
  baseline at the stamped revision before treating a pending-created table as
  leaked, preventing legitimate tables from the other parent being dropped.
  Data-bearing blockers and unavailable migration machinery are refused before
  destructive work.
- Gate: **44 passed, one warning** (96.39s), covering vendor accounting, repair
  refusal/no-op/linear cleanup, executable remedy, packaging and the adapted
  migration join. Ruff and whitespace checks passed. The later disposable
  PostgreSQL 17 recovery/refusal and parity gates supersede this checkpoint's
  SQLite-only limitation; full-suite validation remains open.

### Email template preview and send-path pass

- `77e2250`, `96b4075`, `de659af`, `117fa65`: integrated a read-only preview
  for unsaved invoice-email edits and the earlier `9885e3c` send-path fix.
  Preview and send share one sandboxed renderer; saved `invoice_email` content
  is actually used, the operator note is escaped and retained, company secrets
  are redacted, blank variables are request-local, and conditional `pay_url` is
  distinguished from names templates can never use.
- Gate: **67 passed, one warning** (13.40s). JavaScript syntax, Black and Ruff
  passed. The later seeded browser smoke rendered this preview and refreshed its
  note inside the sandbox; live SMTP remains deferred.

### Windows CI and macOS HarfBuzz follow-up

- `ced37f8`, `52ae865`, `95c782c`, `f1c8dae`: added a Windows 3.13 portability
  lane with named tests, a 300-second per-test timeout and skip budget. Preserved
  the local Linux PostgreSQL service, frontend gate and tighter lint pins. The
  POSIX parent-watcher process test is skipped on Windows, where `os.kill(pid,
  0)` has destructive semantics.
- `d037eeb`: replaced post-analysis library removal with early exclusion of
  Pillow's font module while retaining exactly-one-HarfBuzz build assertions.
- Gate: **35 passed, one warning** (2.84s); workflow YAML parsed, Black, Ruff
  and whitespace checks passed. Hosted Windows and native macOS builds remain.

### Vocabulary composition and audit-tool pass

- `8060653`, `3065b8d`, `bb6a9db`, `f9c98be`: integrated company-type wording
  at the HTTP boundary, control-account guidance, AI labels and analytics empty
  states. Posting/payment/recurring/void/late-fee descriptions now use each
  document's actual face, so a nonprofit pledge and an ordinary invoice remain
  distinct and historical ledger wording is stable.
- `81606a7`, `71675e7`, `1244f26`, `0af5ad8`: incorporated the vocabulary
  walker with seeded-data/Jinja exclusions, live chart discovery and an
  environment-only password. No credential or default password was added.
- Gate: **82 passed, one warning** (33.05s), covering vocabulary, document
  references, email rendering and vendor credits. JavaScript syntax, Black and
  Ruff passed; whitespace was corrected after the gate. The later seeded live
  dual-mode walker supersedes this checkpoint's walker deferral; broader browser
  acceptance remains deferred.

### Consecutive packaging, documentation and fixture pass

- `79150e3`: integrated bounded timestamp-failure retries (three attempts,
  30/60-second backoff), with other signing failures immediately propagated.
  Both app and DMG signing use the helper. Build identity now includes the
  12-character commit SHA, with CI verification; tests exercise CI/local/unknown
  provenance without building. **27 passed, one warning** (0.59s); all signing
  calls and retry sleeps mocked. Native signing/provenance acceptance remains
  separate; no workflow or release command was run.
- `c112232`: integrated control-account guidance, adapted to later account
  cleanup: names remain editable, numbers/types protected, and ordinary unused
  seeded accounts can be deleted. Did not reinstate the older blanket seeded-
  account deletion ban. README unchanged.
- `58870d5`: integrated the reusable audit-hook session factory while retaining
  a fresh database per test. Deliberately retained client lifespan execution:
  removing startup across this larger local suite would alter the deferred full
  validation baseline. No claim of upstream's measured memory/time improvement.
  Added repeated-fixture checks for factory identity, empty databases and exactly
  one audit record per insert. Fixture/audit/control/banking/desktop gate:
  **101 passed, one warning** (101.79s). Black **639 files**, Ruff and whitespace
  checks passed. Full-suite validation and measured memory profiling remain open.

### Native PDF scanning integration

- `a38cca2` release-helper remainder integrated: failed checked commands print
  both captured streams and preserve them on CalledProcessError, so a signing
  failure retains diagnostics. Command-line identity redaction remains intact;
  captured tool streams remain release evidence, not generally sanitized text.
  New tests cover failure diagnostics, successful commands and unchecked failures.
  macOS release/packaging gate: **20 passed, one warning** (0.53s); targeted
  Black, Ruff and whitespace checks passed. All commands mocked; no signing,
  notarization, upload or native build ran.
- Integrated `b16dbb0` runtime: page-1 rendering through Windows.Data.Pdf or
  macOS Quartz, with Poppler fallback, renderer discovery in `/api/ocr/status`
  and Settings, and the pinned Windows PDF projection dependency. Preserved
  existing OCR intake validation, storage isolation, parsing and cleanup guards.
- Included `a38cca2`'s Quartz/ImageIO capability probe and `09f0ad5`'s corrected
  WinRT options overload. Separate packaging/release changes remain pending;
  the headless launcher portion is now integrated below. This is not
  Windows/macOS installed-artifact acceptance.
- Adaptation: only the explicit `PdfRasterError` marker exposes authored
  renderer wording. Ordinary library ValueErrors are sanitized too; process
  launch failures never include their raw exception text. Added regressions for
  both cases. Existing timeout, first-page and temporary-cleanup checks retained.
- Incorporated `32c899e`'s host-independent raster fixtures and isolated the
  earlier Poppler-only tests from native engines. New tests cover fake WinRT,
  ImageIO detection, native preference/fallback, platform-specific unavailable
  messages, status reporting and a real Poppler PDF-to-PNG render.
- Gates: **126 passed, one warning** (11.86s), then expanded OCR/conversion/
  intake/storage/subprocess gate **146 passed, one warning** (28.74s). Black
  **633 files**, Ruff, Settings JS syntax and whitespace checks passed. No full
  suite or native Windows/macOS execution; README/release version left alone.

### Banking integration checkpoint

Desktop follow-up (`09f0ad5`): headless and smoke launches now pass
`persist=False`, leaving the desktop DATABASE_URL/last-opened selection alone;
windowed launches still persist. Retained local LAN TLS requirements, TLS health
probes and child cleanup on failed startup. The upstream test initially stopped
at our stricter TLS guard; adapted its setup without weakening that guard and
added explicit TLS-refusal/cleanup assertions. Also sanitized URL-parser and
stored-image decode exceptions without logging potentially private image details.
Gates: **49 passed, two dependency skips, one warning** (23.41s), plus AI
transport/security **64 passed, one warning** (0.30s). The skipped region tests
require their native OCR tools; no native desktop artifact was built. Windows
version-resource/workflow integration is now completed below.

Windows metadata follow-up: integrated the import-free VSVersionInfo generator,
PyInstaller `EXE(version=...)` wiring and a pre-signing workflow check for exact
FileVersion/ProductVersion/ProductName. The existing app version is unchanged;
generated resource text is ignored. Added executable resource-expression tests
and static build/workflow wiring checks; adopted UTF-8 reads from `81416c0`.
Gate: **15 passed, one warning** (1.72s), including macOS packaging and launcher
regressions; targeted Black, Ruff and whitespace checks passed. No workflow,
signing, installer build or Windows-native metadata inspection was performed.

- Integrated the coordinated `2d200b0`–`dda9e48` runtime group: ledger-derived
  balances/register, explicit bank/card posting and transfers, imported-statement
  review queue, ledger-line reconciliation and the unified Banking page.
  This replaces the old side ledger; it does not replace the earlier validation
  record. Categorization alone deliberately neither posts nor matches a line.
- Retained local row-lock and account/date-isolation safeguards while adapting
  reconciliation tests to ledger-line IDs. Register entry IDs remain transaction
  IDs; statement queue IDs are a separate namespace. Existing ownership, totals,
  locking and import-idempotence checks were adapted, not discarded.
- Added local migration join `ac14bd25ce36` for `fb23cd45ef67` and banking
  revision `e7f8a9b0c1d2`, without changing published revisions. One current
  Alembic head; disposable SQLite upgrade/downgrade checks passed. The later
  vendor-credit migration still needs integration and graph review.
- Compatibility gate: **25 passed, one warning** (10.68s). Broader banking,
  SimpleFIN, cash-route, journal, report and wiring gate: **98 passed, four
  skipped, one warning** (29.04s). Missing-control-account expectations now
  assert actionable 409 responses; rule tests assert categorization without a
  ledger link. Four PostgreSQL concurrency tests require a dedicated test DB.
- Reproduced a manual-match defect: an already-voided expense was accepted
  despite being excluded from automatic candidates. Added rejection of both
  voided originals and reversals, with an HTTP regression checking unchanged
  statement and clearing state. Follow-up banking/import/migration gate:
  **34 passed, one warning** (14.90s); targeted Black, Ruff and whitespace
  checks passed after the fix.
- Navigation follow-up: register links previously targeted absent detail routes.
  Added invoice/bill/payment/journal routes using existing document views;
  standalone postings (including transfers and bill payments) now open the
  exact transaction's journal view, not a source ID or nonexistent page. Invalid
  IDs are rejected before controller calls. Removed nested navigation from the
  legacy Check Register route, which could overwrite Banking with empty HTML.
  Gate: **32 passed, one warning** (5.59s), plus **27 frontend tests passed**.
- Void-lock follow-up: expense and manual-journal routes bypassed the line
  locks in the shared void helper. The common reconciliation guard now locks
  lines in ID order and refreshes them before checking, for every caller.
  Added route lock checks and simulated stale-cache rejection (not a live
  concurrency test). Gate: **33 passed, one warning** (26.92s). Black **628
  files**, Ruff, JavaScript syntax and whitespace checks passed.
- Matching follow-up: automatic matching now revalidates its selected candidate
  through the manual-match guards, rather than directly linking a stale lookup.
  Match and unmatch lock and refresh the ledger line before checking ownership,
  amount, existing claims and reconciliation state. Five new regressions cover
  candidates reconciled/claimed/changed after discovery and stale cached state
  in both mutation paths. Matching/import/SimpleFIN gate: **62 passed, one
  warning** (8.22s). Black **629 files**, Ruff and whitespace checks passed.
  These are deterministic state/lock tests, not live concurrent transactions.
- Batch/lock-order follow-up: automatic matching and add-all now claim current
  eligible statement rows in ID order using `SKIP LOCKED`, refreshing cached
  values. Matching/unmatching also skip busy ledger rows: manual operations
  return retryable 409, automatic operations leave them queued. This avoids
  waiting on a void's ledger lock while holding the statement lock it needs.
  Expanded matching/import/reconciliation/report gate: **80 passed, one warning**
  (37.37s). Black **631 files**, Ruff and whitespace checks passed.
- Real database gate: a disposable PostgreSQL 17 container, loopback-only and
  synthetic data, ran five new independent-connection locking cases plus the
  existing accounting/audit concurrency suite: **13 passed, five skipped, one
  warning** (23.15s). Skips were SQLite variants of PostgreSQL-only cases; the
  previously skipped PostgreSQL accounting cases executed. Verified busy ledger
  match/unmatch/auto behavior and competing auto/add-all statement claims.
  The temporary container and its memory-backed database were removed afterward.
- Still open: remaining cross-operation banking races, PostgreSQL migration
  acceptance, browser acceptance, later banking follow-ups and deferred full
  validation. These six rows remain partial, not release-certified.

### Cash-flow integration

- Incorporated `43414fb` with `ab35f72`: only counterpart lines of journals
  touching bank-kind cash contribute; cash-to-cash transfers, non-cash accruals
  and native opening balances do not inflate period flow. Kept upstream's
  corrected investing sign. The follow-up deliberately uses chart `bank_kind`,
  not feed linkage or active status, preserving feedless and historical banks;
  cards are liabilities, not cash.
- Adopted the upstream balanced-journal regression and added card-payment,
  inactive-bank-history and date-boundary coverage. Adapted the older report
  fixture to mark its cash account explicitly and expect actual cash movement
  (103), rather than non-cash expenses in operating flow. Included in the
  **80-pass** gate above. `d853dc9` first-parent effects reviewed; its runtime
  and test files equal its second parent, with no extra conflict resolution.

### Verified findings from the first implementation batch

- `2fd6758`: reproduced plaintext credential exposure in an editable donor
  acknowledgment subject before the fix. Shared redaction and registry aliases
  are integrated. New regressions cover all 11 encrypted settings keys through
  direct lookup and whole-dictionary rendering, with source credentials left
  intact. Combined donor/settings/email gate: **64 passed, one warning**.
  The later editable-invoice context builder now shares this redaction path and
  is covered by the 67-test template/security gate.
- `dba2839`: new PostgreSQL company creation now calls the existing migration
  and chart-seeding initializer. Quoting tests remain; added failure coverage
  verifies no master registration or private error exposure. Company/desktop
  gate: **110 passed, one warning**. Connections mocked; no live PostgreSQL
  acceptance claimed. `7bfaa88` is its merge wrapper; `bf69d6c` formats tests.
- The committed-tree preview's migration graph has **two heads**,
  `fb23cd45ef67` and `f8a9b0c1d2e3`, with no missing parent revisions.
  Verified by statically parsing revision declarations from tree
  `fc0ae980525a5cd1142607901fe0f00b7d6b2174`; no migration code was executed.
  A clean textual merge would not eliminate this integration blocker.
- `fe68262`, `01ceea7`, `0cb9188`, `7f64bc0`: QBO/IIF route and row handlers
  now sanitize failures through fixed route messages and the shared helper.
  Integrated the final explicit `DataProblem` marker for authored IIF messages,
  including this branch's cross-customer payment guard. Adaptation: database
  constraint responses never include the driver's first line, which can contain
  rejected values. Follow-up integrated QB-report, widget, settings-email,
  invoice-email and typed donor-error handling, plus accounting/job-cost/
  time-entry and import-parser markers. The control-account-specific part of
  `7f64bc0` is now integrated with the typed control-account handler. This is not a claim
  of repository-wide error sanitization or a completed CodeQL run.
- `f180777`: superseded by the PDF integration gate below; WeasyPrint 70.0
  and the class-based data-only fetcher are now integrated and tested locally.
- `7c0d274`: exact QBO callback exemption integrated with the auth-contract
  justification. Tests cover cookie-free success, state consumption, missing/
  incorrect/replayed state, protected neighboring routes and no provider calls
  for invalid state. Adaptation: callback ValueErrors are sanitized too, not
  passed through just because they are ValueErrors. Live-provider acceptance
  remains separate.
- Checks after the first batch: Black **595 files**, Ruff and whitespace
  checks passed. Full-suite, merged-tree and platform acceptance remain open.

### Rationale retained in the error-handling integration

- `fe68262` addresses exposed SQL/provider details but deliberately retains the
  donor's actionable ineligibility explanation. Adopted `NotAGift.reason` and
  kept our independently added credential redaction in the same donor service.
- `0cb9188` identifies two less obvious disclosure paths: errors inside a
  successful dashboard response and persisted invoice EmailLog rows. Both now
  use sanitized text. Tests prove a failed widget does not hide healthy cards,
  and an invoice rendering failure creates one sanitized failed-email record.
- `7f64bc0` supersedes the intermediate assumption that all ValueErrors contain
  operator-safe wording. Adopted explicit DataProblem markers without removing
  local finite-number, missing-account or cross-customer checks. It remains a
  ValueError subclass, preserving existing rejection/catch behavior. Two old
  test expectations failed because they echoed arbitrary ValueErrors; tests now
  exercise BOTH preserved DataProblem wording and sanitized ordinary ValueErrors.
- Kept the local stricter driver policy: never expose a constraint's first
  driver line, since it can contain rejected values. This is an intentional
  adaptation of upstream's implementation, not rejection of its disclosure fix.
- Third-batch gates: **98 passed, one warning** (44.39 seconds), covering
  donor/email/QB reports/redaction; **53 passed, one warning** (5.95 seconds),
  covering accounting/time-entry/job-cost/import helpers. Black **597 files**,
  Ruff and whitespace checks passed. No SMTP/provider calls or full suite.

Second batch verification: callback/auth selection **49 passed, 515 deselected,
one warning**; combined QBO/IIF/helper regression gate **169 passed, one warning**
(23.02 seconds). Black **597 files**, Ruff and whitespace checks passed.
No live-provider calls or full-suite rerun. The initial textual probe column is
historical and was not recomputed after local integrations.

### Control accounts and account/email UI integration

- `7caa195` / `ebfd281`: protect literal posting-account numbers/types, allow
  renaming, expose derived control metadata and lock only the protected form
  fields. Missing accounts raise an authored 409 before a document is accepted;
  startup diagnoses missing seeded accounts without preventing chart repair.
  Export display lookups remain tolerant. Preserved local accounting guards,
  middleware placement and sanitized handler text. Six old helper assertions
  expected silent `None`; updated to require the typed failure. Gate: **125
  passed, one warning** (32.64s), plus **10 frontend checks**.
- `e95cfed` / `724acdf`: unused ordinary seeded accounts can be deleted;
  controls, posted history and schema-discovered references remain protected.
  Deactivate/reactivate/show-inactive controls are integrated together with the
  numeric-ID-only delete handler, avoiding upstream's broken quoted attribute.
  Gate: **70 passed, two skipped, one warning** (18.95s). The two upstream skips
  concern on-demand accounts 4800/5900. The metadata sample uses local budgets
  instead of not-yet-integrated vendor credits; the implementation scans every
  loaded account foreign key. HTML-parser checks are not browser acceptance.
- `e95cfed` / `3690ec1` / `cc5dc87`: invoice email accepts the dialog's message,
  escapes it in both template and fallback, and still rejects unknown fields.
  Adapted the host-dependent test to stub PDF/SMTP and require successful send
  with the actual rendered message, rather than accepting any handler 500.
  Email/helper gate: **26 passed, one warning** (3.78s). Earlier 24-test gate
  also passed Ruff/whitespace checks. No external email was sent.
- These are focused integration gates, not full-suite or release certification.
  README unchanged. No merge, commit, push, PR or live database migration.

### Import, clipboard and PDF integration

- `4e527b4`: real Wave Account Transactions headers now resolve account names
  and nonzero amounts; GL filename fragments precede generic account fragments.
  Preserved authored-error and import safeguards. Wave/common-parser/clipboard
  source gate: **17 passed, one warning** (4.86s). Merge `0027050` has the same
  three-file first-parent effect; no separate conflict-resolution delta.
- `b893e72` / `b870ce9`: token Copy and all four shared clipboard call sites
  integrated. Insecure-context and permission failures give manual recovery;
  visible token text is selected without placing it in a toast. Added five
  executable controller tests beyond upstream's source guards; all **15 frontend
  tests** passed. Merge `9559d64` has the same settings-only first-parent effect.
- `f72be37`: company logos reach all seven document templates via the shared
  renderer, retaining upload-root/MIME restrictions and local currency rounding.
  Initial PDF/logo/security gate: **33 passed, one warning** (2.64s).
- `f180777` / `142d407` / `d03c058`: requirement and local venv upgraded to
  WeasyPrint **70.0**; class-based fetcher enforces data-only protocols and loads
  lazily. Windows/macOS specs explicitly retain the engine. Native-stack skip
  support integrated; a subprocess proves ordinary PDF-service import succeeds
  with WeasyPrint blocked while actual rendering still requires it. Adapted old
  callable-option mocks to the new header/protocol interface. The invoice-email
  signature regression stubs PDF rendering instead of skipping on missing native
  libraries. Final PDF/report/packaging/API gate: **85 passed, one warning**
  (14.71s). Black **607 files**, Ruff and whitespace checks passed. No native
  Windows/macOS artifact build or whole-suite missing-stack run claimed.

### Attachment/UI follow-up

`0d67176` portable stored paths integrated while keeping unique upload filenames
and exclusive creation. Adaptation: absolute POSIX, Windows drive and UNC paths
remain rejected before separator normalization; traversal tests cover both
separators. The `32c899e` route ordering was already correct locally; added HTTP
and mounted-route-shadow checks, plus hidden-class and Quick Entry theme fixes.
Its later rasterizer fixture is integrated with the OCR/packaging group. `d2ae5ed` link/success/
footer tokens integrated; the local footer-link override now inherits the
repaired theme color. Focused gate: **36 passed, one warning** (9.32s), including
upload/download/delete, CSS contrast and accessibility guards. Ruff, JS syntax
and whitespace checks passed. Not a full browser AA audit. `0d67176` platform-test
portions remain for the OCR/packaging group.

### Per-commit status

Sidebar/encoding follow-up: `65e905e` moves the update banner and running version
to the sidebar header while retaining the footer version and nonblocking empty
state. Its OCR fixture is integrated; release metadata is superseded. `81416c0`
UTF-8 reads are applied to all affected call sites, including the later Windows
version-resource coverage. Gates: **53 passed, one warning** (11.50s) for control/UI/report
regressions, **31 passed, one warning** (5.83s) for auth/subprocess/terminology.
Added five account-controller tests covering actual rendered ID-only handlers,
cancel/refusal/success deletion and reactivation: all **20 frontend tests** pass.
Black **609 files**, Ruff and whitespace checks passed. No Windows-host run or
full-suite result claimed. `967bcfa` first-parent diff matches the already
integrated callback exemption and auth-contract test.

| # | Commit | Upstream subject | Kind | Initial textual probe | Disposition / evidence |
|---|---|---|---|---|---|
| 1 | `f72be37` | fix(pdf): the company logo on every document, not only the analytics PDF | change | neither applies cleanly | Runtime/tests integrated; concise feature/CHANGELOG effect recorded and release metadata superseded |
| 2 | `fe68262` | fix(security): exception text stays in the server log, not the response | change | forward-check passes | Integrated with final typed-error policy; donor reasons and QB-report rollback retained |
| 3 | `da9e217` | release: 2.9.4 — company logo on every document; exception text stays in the log (version, changelog, what's new) | change | neither applies cleanly | Runtime children and concise CHANGELOG effect incorporated; version/What's New metadata superseded by the local unreleased integration |
| 4 | `01ceea7` | fix(security): exception text out of every importer's row errors, not only the route | change | neither applies cleanly | Runtime integrated/adapted including settings email; concise CHANGELOG effect recorded and release metadata superseded |
| 5 | `0cb9188` | fix(security): Python's own errors are bugs, not user messages; two more echo sites | change | neither applies cleanly | Integrated using later explicit-marker policy; widget and persisted email errors tested |
| 6 | `dba2839` | fix(companies): migrate + seed new Postgres company DBs (alembic head + chart of accounts) | change | forward-check passes | Integrated; shared migrate/seed helper; 110-test gate passed |
| 7 | `7bfaa88` | Merge pull request #113 from MkInc42/fix/create-company-seeds-chart-of-accounts | merge | forward-check passes | Merge wrapper; dba2839 implementation and tests adapted |
| 8 | `bf69d6c` | style: black on tests/test_company_service_dbname.py (CI lint after #113) | change | neither applies cleanly | Formatting intent satisfied; local Black check passed |
| 9 | `2d200b0` | banking: bank_kind on the chart + the 2.10 schema migration (#114) | change | forward-check passes | Incorporated/adapted: schema plus explicit local migration-head join; SQLite graph gate passed, live PostgreSQL upgrade acceptance remains a release gate |
| 10 | `6ec0dd1` | banking: the register and every bank balance come from the ledger (#114) | change | forward-check passes | Incorporated: GL register/balances and corrected source links tested; live/browser acceptance remains a release gate |
| 11 | `a94d241` | banking: register entries, transfers and card charges post (#114) | change | neither applies cleanly | Incorporated/adapted: posting/void routes, row locks and source links tested, including live PostgreSQL locking gate |
| 12 | `5a98688` | banking: statement lines become a review queue (#114) | change | neither applies cleanly | Incorporated/adapted: queue/rules/import, manual void-match guard, atomic batch claims and retry behavior tested |
| 13 | `2ade934` | banking: reconcile over the ledger's lines (#114) | change | neither applies cleanly | Incorporated/adapted: GL reconciliation with account/date isolation and refreshed row locks; live PostgreSQL locking gate passed |
| 14 | `dda9e48` | spa: one Banking page — register, review queue, transfers, reconcile (#114) | change | forward-check passes | Incorporated: unified page, wiring and executable navigation checks passed; full browser acceptance remains a release gate |
| 15 | `c48b418` | release: 2.10.0 — the bank register is the ledger (version, changelog, what's new, docs/banking.md, features, data model, bank-feeds setup) | change | neither applies cleanly | Runtime and detailed banking/data-model docs incorporated with local safeguards; release version/What's New and expanded README superseded |
| 16 | `43414fb` | Fix cash flow to follow linked bank journals | change | neither applies cleanly | Incorporated with ab35f72 bank-kind adaptation; cash-flow regressions passed |
| 17 | `b16dbb0` | ocr: PDF receipts scan on Windows and macOS with nothing to install (#116) | change | neither applies cleanly | Runtime/dependency/status integrated with stricter errors; 146-test gate passed; release metadata superseded and native artifact acceptance remains a release gate |
| 18 | `f180777` | deps: WeasyPrint 69.0 -> 70.0 (CVE-2026-55073) and a fetcher the library enforces everywhere | change | neither applies cleanly | Integrated with lazy-loading follow-up; 70.0 installed; 85-test gate |
| 19 | `10493fa` | Merge branch 'feat/bank-register-ledger' into pr117 | merge | neither applies cleanly | Merge wrapper reviewed; rows 9–18 carry the adapted runtime, migration, UI, docs and test dispositions |
| 20 | `ab35f72` | reports: cash flow keys "cash" off Account.bank_kind for 2.10 (on top of #117) | change | neither applies cleanly | Incorporated: feedless/historical bank cash, cards excluded; focused gate passed |
| 21 | `d853dc9` | Merge PR #117: cash flow follows the cash journals (jsonmez) | merge | neither applies cleanly | Reviewed wrapper: first-parent cash-flow effects incorporated; runtime/tests equal second parent |
| 22 | `a38cca2` | ocr/macos: the renderer probe proves ImageIO is there; release.py surfaces what codesign said | change | neither applies cleanly | Incorporated: ImageIO probe and release failure diagnostics tested; native artifact acceptance separate |
| 23 | `09f0ad5` | Windows PDF scan renders (#116 check 9), exe version resource (#106), headless launches keep desktop state (#110), two error strings in our own words (#111) | change | neither applies cleanly | Incorporated/adapted: raster, headless state, error wording and Windows metadata/workflow locally tested; native artifact acceptance separate |
| 24 | `79150e3` | macos release: retry Apple's timestamp service only; the bundle says which commit it is (testing-repo #28) | change | neither applies cleanly | Incorporated: bounded retry and SHA provenance; 27-test mocked packaging gate passed; native acceptance separate |
| 25 | `e198454` | README: a What's New section for v2.10, and the API operation count | change | neither applies cleanly | Intentionally superseded by the requested light README; detailed release and operation evidence stays in CHANGELOG/docs |
| 26 | `18f59b2` | Merge pull request #118 from VonHoltenCodes/docs/2.10.0-readme | merge | neither applies cleanly | Merge wrapper reviewed; child README expansion intentionally superseded by row 25 |
| 27 | `7caa195` | A document is never accepted without its journal entry (#119) | change | neither applies cleanly | Integrated; typed control failure, edit guards and tolerant export display; 125-test gate |
| 28 | `81416c0` | read_text(encoding="utf-8") everywhere (#119, reporter's note 2) | change | neither applies cleanly | Available call sites integrated; macOS test already compliant; absent version-resource test follows its feature |
| 29 | `c112232` | docs: control accounts — what may be renamed, what may not, and why | change | forward-check passes | Incorporated/adapted to later cleanup: ordinary unused seeded accounts may be deleted |
| 30 | `3bdcf44` | Merge pull request #120 from VonHoltenCodes/fix/control-accounts-fail-loud | merge | neither applies cleanly | Merge wrapper reviewed; control-account runtime/docs/tests incorporated by rows 27–29 with stricter local guards |
| 31 | `142d407` | tests run on a machine without WeasyPrint's native stack (#121) | change | neither applies cleanly | Integrated/adapted; lazy import, native-stack hook, deterministic email signature test |
| 32 | `d03c058` | packaging: name weasyprint in both specs now that its import is lazy (#121) | change | forward-check passes | Integrated; both specs retain explicit hidden import; artifact builds deferred |
| 33 | `ebfd281` | The Chart of Accounts offers the rename 2.10.1 promised (#122) | change | neither applies cleanly | Integrated; derived control flags, Edit all accounts, number/type locks |
| 34 | `58870d5` | tests: stop the suite retaining ~500 MB per run (#124) | change | forward-check passes | Adapted: reusable factory, fresh databases; lifespan removal intentionally not adopted; no memory benchmark claim |
| 35 | `0d67176` | Windows portability: an attachment path bug, and six tests that could only fail there (#121) | change | neither applies cleanly | Incorporated/adapted: portable attachment paths and available platform/OCR regressions; Windows CI lane integrated, native host acceptance remains separate |
| 36 | `ced37f8` | CI: run the suite on Windows (#121) | change | forward-check passes | Incorporated/adapted: Windows 3.13 portability lane; local Linux PostgreSQL/frontend gates retained |
| 37 | `52ae865` | CI(windows): name each test and add a per-test timeout, to find where the run dies | change | neither applies cleanly | Incorporated: verbose names and per-test timeout |
| 38 | `95c782c` | tests: the parent-watcher test kills the Windows CI process (#121) | change | neither applies cleanly | Incorporated: POSIX-only process test skips on Windows |
| 39 | `f1c8dae` | CI(windows): the migration tests are slow here, not hung — raise the timeout | change | neither applies cleanly | Incorporated: 300-second timeout and skip budget |
| 40 | `65e905e` | 2.10.3: the update notice moves to the top of the sidebar, and Keith's host-dependent test | change | neither applies cleanly | Sidebar runtime and host-independent OCR fixture integrated; release metadata superseded |
| 41 | `32c899e` | Attachments open again, the search panel closes, and the Quick Entry log is readable | change | neither applies cleanly | Incorporated/adapted: existing route order HTTP-tested, CSS fixes and isolated raster fixtures integrated; focused gates passed |
| 42 | `39d03b4` | CHANGELOG: the four gate findings, and remove a duplicate 2.10.3 heading | change | neither applies cleanly | Findings incorporated concisely in Unreleased; current changelog has no imported duplicate 2.10.3 section |
| 43 | `d2ae5ed` | Dark theme: the three contrast causes from macbase1's sweep (#41) | change | neither applies cleanly | Integrated; theme tokens, bare links, footer and local footer-link adaptation tested |
| 44 | `9c7ebdb` | vendor credits: the AP-side counterpart of a credit memo (#129) | change | neither applies cleanly | Incorporated/adapted: full AP credit workflow, aging parity and local migration join; 27 feature tests, 44 combined gate |
| 45 | `4e527b4` | Fix Wave Account Transactions report import (blank GL account + misclassification) | change | forward-check passes | Integrated; actual filename/header dry-run and local parser regressions passed |
| 46 | `b893e72` | Add a Copy button for newly-created API tokens | change | forward-check passes | Integrated with shared-helper follow-up and executable clipboard tests |
| 47 | `0027050` | Merge pull request #134 from rchanks/fix/wave-account-transactions-report-headers | merge | forward-check passes | Wrapper verified; first-parent effect matches 4e527b4 |
| 48 | `9559d64` | Merge pull request #135 from rchanks/fix/api-token-copy-button | merge | forward-check passes | Wrapper verified; first-parent effect matches b893e72 |
| 49 | `3310656` | release: 2.11.1 — two fixes from @rchanks, both found against real work | change | neither applies cleanly | Wave/API-token children and concise attribution incorporated; version/What's New metadata superseded by local unreleased integration |
| 50 | `e95cfed` | accounts: an operator can shrink a chart they did not choose (#139, #140) | change | neither applies cleanly | Runtime/tests integrated with follow-ups; release metadata deferred |
| 51 | `3690ec1` | tests: my email assertion was host-dependent — the Windows job caught it | change | neither applies cleanly | Adapted; deterministic PDF/SMTP stubs and actual message assertion |
| 52 | `cc5dc87` | tests: take @macbase1's control assertion into the product suite | change | neither applies cleanly | Integrated as HTTP unknown-field rejection test |
| 53 | `b870ce9` | WIP for #137: one clipboard helper, all four call sites on it | change | neither applies cleanly | Integrated; four call sites, source guards and five new controller tests |
| 54 | `9885e3c` | 2.12.0: close #132, #137, #139, #140 and #141 together | change | neither applies cleanly | Runtime children incorporated with local safeguards, including the final pre-analysis macOS HarfBuzz exclusion; release metadata superseded |
| 55 | `2fd6758` | security: an editable email template could read stored credentials | change | neither applies cleanly | Incorporated across donor and final invoice-email renderers; shared secret registry and 67-test template/security gate |
| 56 | `d037eeb` | #141: exclude the module, do not drop the library — @macbase1's measurement | change | neither applies cleanly | Incorporated: exclude Pillow font modules before Analysis; retain exact-one-HarfBuzz guards; 35-test combined gate |
| 57 | `956f17a` | #132: repair a half-upgraded file, because the refusal's advice could not work | change | neither applies cleanly | Incorporated/adapted: merge-safe SQLite baseline plus dependency-aware PostgreSQL recovery; real PG recovery/data-refusal and parity gates passed |
| 58 | `724acdf` | #139 HIGH: the Delete button never fired — mine, and the release headline | change | neither applies cleanly | Integrated with account cleanup; numeric handler and markup checks |
| 59 | `627ebe9` | docs: bring the parked design notes onto main and retire their branches | change | forward-check passes | Incorporated/adapted: both notes added and indexed alongside existing shipped/spec design records without implying product commitment |
| 60 | `77e2250` | Preview an email template edit before saving it | change | neither applies cleanly | Incorporated with shared sandboxed send renderer; 67-test gate |
| 61 | `847cdb0` | Merge pull request #147 from mdornich/feat/email-template-editor-preview | merge | neither applies cleanly | Merge wrapper reviewed; child preview effect incorporated by `77e2250` disposition |
| 62 | `adf29d4` | Merge pull request #145 from VonHoltenCodes/docs/park-design-notes | merge | forward-check passes | Merge wrapper reviewed; row 59 documents the adapted notes/index effect |
| 63 | `f7923ef` | release 2.12.1: bundle the repair script (#144), and @mdornich's editor preview | change | neither applies cleanly | Runtime/package effects incorporated; release version/What's New intentionally superseded by local unreleased ledger |
| 64 | `6dcca59` | #144 again: the script shipped and nothing could run it — plus a 2^N repair | change | neither applies cleanly | Incorporated/adapted: executable frozen/source entry point and linear merge-graph-safe repair |
| 65 | `96b4075` | preview: say what rendered as nothing (@macbase1, 2.12.1 gate) | change | neither applies cleanly | Incorporated: rendered blanks reported without changing output |
| 66 | `de659af` | preview: per-request recording, and the editor's hint told the truth (@skytech) | change | neither applies cleanly | Incorporated: ContextVar isolation and truthful variable hint |
| 67 | `2a7bd24` | repair: set DATABASE_URL before the import, and refuse before destroying | change | neither applies cleanly | Incorporated/adapted: URL set before import; preflight plus local disposable baseline before drops |
| 68 | `117fa65` | preview: tell the two kinds of blank apart (@skytech, 2.12.1 gate) | change | neither applies cleanly | Incorporated: unavailable versus conditional blanks tested in 67-test gate |
| 69 | `fa3f5a7` | feat(import): support Bank of America detail CSV | change | neither applies cleanly | Incorporated/adapted with finite amounts and later guards; parser/queue/dedup tests passed |
| 70 | `dcd3a3f` | test(import): add verified BoA detail fixture | change | neither applies cleanly | Incorporated: exact upstream fixture bytes and CRLF attributes; provenance attributed to upstream |
| 71 | `55fa0f9` | banking: bound the CSV header scan, and drop BofA balance rows by name | change | neither applies cleanly | Incorporated: bounded search and metadata guards; end-to-end signs tested |
| 72 | `2bc2bcd` | banking: the Bank of America importer is no longer parked | change | neither applies cleanly | Incorporated: feature documentation names supported detail format |
| 73 | `7f64bc0` | errors: only a sentence written for the user leaves the process | change | neither applies cleanly | Integrated/adapted; explicit service/route and control-account markers; stricter driver sanitization retained |
| 74 | `1e3d596` | launcher: say what a machine without WebView2 can do (#149), and serve on a 1 ms timer on Windows (#107) | change | neither applies cleanly | Incorporated/adapted: usable frozen/source guidance and loopback browser fallback; timer finalized by `0a078c2`; local TLS/cleanup retained; 49-test simulated gate |
| 75 | `06f2e27` | tests: one engine and one schema for the whole run, per-test rollback (#128) | change | neither applies cleanly | Intentionally adapted/superseded: reuse the session factory but retain fresh per-test engines and lifespan coverage to protect isolation; whole-suite memory benchmark deferred |
| 76 | `0c114d4` | tests: release the event loops anyio's run registry keeps alive | change | neither applies cleanly | Incorporated: guarded closed-loop registry cleanup; existing lifespan/fresh-engine contract retained; 57-test gate |
| 77 | `4d087b2` | release 2.13.0: Bank of America, in a file the bank produced | change | neither applies cleanly | Runtime children incorporated/adapted; release version/What's New superseded; fixture memory goal remains deferred |
| 78 | `0a078c2` | gate 2.13.0: the import dialog says it is working, names Bank of America, and the 1 ms timer is opt-in | change | neither applies cleanly | Incorporated/adapted: import feedback/label plus opt-in, matched-cleanup Windows timer; 29 frontend and 49 launcher tests |
| 79 | `addcd2c` | gate 2.13.0: the Import button is handed in, not found by focus (@macbase1) | change | neither applies cleanly | Incorporated/adapted: explicit button, finally restoration and duplicate-call guard; executable tests passed |
| 80 | `33defcb` | tests: read the page and the packaging script as UTF-8, not the console codepage | change | neither applies cleanly | Incorporated/equivalent: launcher test explicitly UTF-8; local Node banking-dialog test already uses `utf8` |
| 81 | `81606a7` | audit: pass A — walk a running server in both company types and report what still carries a business word | change | forward-check passes | Incorporated/adapted and run live against seeded business/nonprofit modes: 2,862/2,853 strings, zero code leaks or unclassified dynamic results |
| 82 | `8060653` | vocabulary: the sentences the server sends follow the company type | change | neither applies cleanly | Incorporated/adapted at HTTP/control/AI/analytics boundaries; 82-test gate |
| 83 | `71675e7` | audit: the walker classes seeded chart names and tax notes as data, not leaks | change | neither applies cleanly | Incorporated: seeded-data/tax-note classification in audit tool |
| 84 | `7c0d274` | Exempt QBO OAuth callback from session-auth middleware | change | forward-check passes | Integrated with sanitized errors; mocked HTTP/state regressions passed |
| 85 | `3065b8d` | vocabulary: what a posting writes for itself is in the company's words | change | neither applies cleanly | Incorporated: document-face references across postings/providers; 82-test gate |
| 86 | `cb8b242` | release 2.13.1: the words the server sends | change | neither applies cleanly | Runtime effects incorporated; release metadata superseded by local unreleased ledger |
| 87 | `967bcfa` | Merge pull request #151 from CimarronSiteServices/fix-qbo-oauth-callback-authwall | merge | forward-check passes | Wrapper verified; callback exemption/auth-contract effect already integrated |
| 88 | `5beb949` | Merge branch 'main' into release/2.13.1 | merge | forward-check passes | Merge wrapper reviewed; child runtime dispositions control |
| 89 | `5f5589e` | release 2.13.1: fold in @CimarronSiteServices' QBO OAuth callback fix (#151, #152) | change | neither applies cleanly | QBO child already incorporated; release metadata superseded |
| 90 | `bb6a9db` | gate 2.13.1: eight more composition sites, found by check 0 on the artifact | change | neither applies cleanly | Incorporated across void/late-fee/payment/recurring sites; 82-test gate |
| 91 | `299e5ac` | tests: the late-fee check sends the invoice first, and reads the ledger with a date range | change | neither applies cleanly | Incorporated in adapted document-reference regression suite |
| 92 | `f9c98be` | vocabulary: a posting says what the document is, not what the company calls documents | change | neither applies cleanly | Incorporated: document face, not global company noun, drives references |
| 93 | `1244f26` | audit: the walker reads the chart from the company and ignores Jinja expressions | change | neither applies cleanly | Incorporated and live-verified; classifier now also attributes composed PDF/chart/tax/history output and walks every harvested real ID |
| 94 | `5249296` | docs: the README at 2.13.1 — what's new is the last three releases, and everyone with code on main is named | change | neither applies cleanly | Intentionally superseded: README remains extremely light; detailed reconciliation lives here/CHANGELOG |
| 95 | `9575f14` | docs: the README's contributor list stays short by design — maintainers here, credit in the changelog | change | neither applies cleanly | Intentionally superseded by current README-light policy and existing credit history |
| 96 | `0af5ad8` | audit: the walker takes its password from the environment, never a default | change | neither applies cleanly | Incorporated: environment-only audit password |
| 97 | `112bb77` | Merge pull request #155 from VonHoltenCodes/fix/walker-no-default-password | merge | neither applies cleanly | Merge wrapper reviewed; child incorporated by `0af5ad8` disposition |
| 98 | `b2927a6` | Merge pull request #154 from VonHoltenCodes/docs/readme-2131 | merge | neither applies cleanly | Merge wrapper reviewed; README child intentionally superseded |
| 99 | `3933146` | legal: license 2.0, contributor terms, and the last QuickBooks-internals remnants gone | change | forward-check passes | Split disposition: nonlegal provenance cleanup incorporated; LICENSE/contributor terms require explicit owner legal acceptance and are intentionally not applied |
| 100 | `d008109` | legal: in whole or in part; no retroactive ask of past contributors (owner's answers) | change | neither applies cleanly | Explicit owner decision required; intentionally not applied without acceptance of the revised legal text |
| 101 | `d5428a6` | Merge pull request #156 from VonHoltenCodes/legal/license-2 | merge | forward-check passes | Merge wrapper reviewed; legal children remain intentionally excluded pending explicit owner acceptance |
| 102 | `c5ddd75` | first launch: the splash shows the terms once, and the installer requires acceptance | change | neither applies cleanly | Legally coupled behavior intentionally excluded until License 2.0 is accepted; current splash/installer must not claim unadopted terms |
| 103 | `3443190` | sign out goes back to the company picker, and the sign-in screen lists the users | change | neither applies cleanly | Incorporated/adapted: active usernames only, picker return with browser fallback, status naming and executable 67-test gate |
| 104 | `645e509` | docs: the sign-in user list belongs under Adding your team | change | neither applies cleanly | Incorporated in Server Edition guide with trusted-network visibility warning |
| 105 | `95b539e` | the window opens straight into the last company; the picker appears by choice | change | neither applies cleanly | Incorporated: first load auto-opens the last company; explicit sign-out returns to a non-auto-opening picker |
| 106 | `1f87e10` | release 2.14.0: in and out of a company, and the terms once | change | neither applies cleanly | Company-selection runtime incorporated; legal terms and release version/What's New metadata intentionally superseded/deferred |
| 107 | `fbf0c2c` | splash: the terms panel gets its background; picker names the company it is opening; companies.js header matches its file | change | neither applies cleanly | Picker naming/header incorporated; terms-panel CSS intentionally excluded with its unaccepted legal dependency |
| 108 | `9bfc378` | the last two invented-heritage headers: style.css and scripts/backup.sh | change | reverse-check passes | Integrated; comment-only patch present |
| 109 | `fe44ddf` | style.css: the section headers stop naming invented QuickBooks classes and offsets | change | reverse-check passes | Integrated; comment-only patch present |
| 110 | `20689c9` | the last heritage comments: about-dialog resource id, dialog style flags, the clock's WM_TIMER, and 'reverse-engineered' on the IIF exporter | change | neither applies cleanly | Adapted; clock comment matches 60-second timer |
| 111 | `7978419` | tests: keep the fixture password away from the username key so GitGuardian's pair detector stops firing | change | neither applies cleanly | Incorporated with the newly integrated sign-in regression file; fixture password is not paired with the username key |
| 112 | `61a9aa1` | docs: README and CONTRIBUTING for 2.14 — what's new, the licence in its own words, how releases are gated, project rules, the test suite as it is | change | neither applies cleanly | Guidance adapted; README expansion superseded by light-README policy and legal claims excluded pending owner acceptance |
| 113 | `12102d6` | Merge pull request #160 from VonHoltenCodes/docs/readme-contributing-2.14 | merge | neither applies cleanly | Merge wrapper; see 61a9aa1 |
| 114 | `2866c90` | Merge pull request #159 from VonHoltenCodes/chore/gitguardian-pair-detector | merge | neither applies cleanly | Merge wrapper reviewed; row 111's fixture adaptation incorporated |
