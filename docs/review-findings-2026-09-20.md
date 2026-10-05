# Local pre-PR review — September 20, 2026

## Final-gate follow-up (September 21 UTC)

After intake through `a1022f8`, concurrent-writer probes reproduced two more
defects, using independent real database sessions:

- Two overlapping migration imports each posted the same two journals on
  PostgreSQL and SQLite. Import now obtains a transaction-scoped advisory lock
  on PostgreSQL or a SQLite write reservation before duplicate/opening-balance
  reads. One writer posts two journals; its competitor posts zero.
- Two SQLite reconciliation starters both created open sessions. SQLite now
  reserves its writer before the open-session check; one succeeds and the
  other receives 409. PostgreSQL's existing account-row lock still passes.

The current follow-up group passes **27 tests**, including both database
backends; related reconciliation/matching/void checks pass **23 tests**, with
five deliberately PostgreSQL-only cases' SQLite variants skipped. The running
full-suite snapshot includes the migration fix but predates the later SQLite
reconciliation fix. It completed 4,859 passed / 11 skipped / one runner-related
failure: an exited watcher child remained a zombie under the runner's non-reaping
PID 1. All 47 launcher/desktop tests pass under `tini -s`; the original failed
run is preserved. Details and snapshot coverage are in current validation.

Fresh default CodeQL scans report **15 Python / 0 JavaScript** findings.
Python rule/path/line identities exactly match the archived default scan.
Bandit remains **0 high / 6 medium / 45 low**, and Gitleaks reports the same
three synthetic fixture keys. No suppressions added. These scanner snapshots
precede the final reconciliation reservation, which was reviewed directly and
tested separately. Formatting, workflow syntax, shell checks, dependency
consistency, repository integrity and 32 frontend tests pass.
Fresh Pyright 1.1.414 with the actual virtualenv still reports **1,888 errors
across 333 files**; this is unchanged debt, not a passing type check.

Inventory includes 218 modified tracked paths and 202 untracked paths; the
untracked set contains 173 tests, 16 application paths, seven docs, three
migrations, two scripts and one packaging helper. Tracked plus nonignored
untracked sources were snapshotted and hashed for scan/review evidence.
Risk-focused review revisited import concurrency, banking/reconciliation,
account hierarchy and filesystem-related scanner sinks. This remains a targeted
review, not an independent code-owner sign-off on every accumulated line.
Browser control again reports no available browser. Native platforms, live
providers, capacity acceptance and owner contributor-term decisions remain
external gates; this pass does not silently accept them.

The sections below retain the preceding review's scope and results.

Scope: uncommitted 2.17.0 tree, incorporating upstream `80f2ad8`.
No PR, commit, push, merge, workflow dispatch or scanner upload was performed.
This supplements the [readiness checklist](local-readiness-2026-09-20.md),
not a certification of enterprise deployment or every API workflow.

Full Linux coverage snapshot: **4,780 passed, 12 skipped, zero failed,
389 warnings**, exit 0, 27m02s; **97.04% statement coverage** (28,605/29,477).
PostgreSQL and native OCR cases ran. The [checklist](local-readiness-2026-09-20.md)
explains skips and the separately verified final edits; no branch-coverage
measurement or exact hosted Ubuntu reproduction is claimed.

## Reproduced defects fixed

- **Account hierarchy:** the ordinary account-edit API accepted an indirect
  parent cycle even though chart import already rejected cycles. Create/edit
  now reject missing parents and cyclic ancestry. Ordered PostgreSQL account
  row locks protect the graph check. A subsequent SQLite contention test
  reproduced two successful reciprocal edits; SQLite now acquires a write
  reservation before reading the graph, matching the accounting lock pattern.
  Regression tests cover the HTTP boundary and two simultaneous reciprocal
  edits on independent sessions on both PostgreSQL and SQLite:
  exactly one succeeds and one is rejected, leaving an acyclic graph.
- **Diagnostic logs:** caught exceptions and operation context could contain
  CR/LF, allowing a single error to imitate additional log records. Safe-error
  logging now escapes context and traceback text into one message. Three
  regression cases cover application data errors, ordinary value errors and
  unexpected exceptions. Public error-response behavior is unchanged; this is
  not a claim that privileged diagnostic logs redact all sensitive data.

Focused final PostgreSQL/account/import/error regression: **93 passed,
2 skipped, 1 warning**, 32.13 seconds. Both skips are control accounts created
on demand rather than seeded. Earlier overlapping focused runs passed 71 and
58 tests; these numbers must not be added together as unique coverage.

The full coverage run uses a frozen checkout containing the initial parent
and log fixes. The later SQLite locking correction, equivalent dictionary
comprehension and two new database-contention cases are covered by the 93-pass
final regression above, not retroactively claimed as part of that full run.
The final host equivalent passed 88 tests with seven skips (five require the
PostgreSQL fixture, which passed in the container; two are seed-data cases).
The SQLite contention regression additionally passed three consecutive reruns;
the account API/bank-kind group passed 27 tests. Counts overlap by design.

## Live final-image acceptance

Image `slowbooks-final-review-217`:
`sha256:d1c8c46c00bfb5bfc0887efd241674f14f369006d3d0585635f88fb300639519`.
The build passed, then the image booted against disposable PostgreSQL 17.
All **35 HTTP checks** passed: parent-cycle/missing-parent rejection; vendor
credit creation, fractional-cent rejection, full application and reversal;
transfer/void and duplicate-void rejection; bank reconciliation and refusal
to void a reconciled expense. Only synthetic records were used. This is the
documented private-network HTTP mode, not a new public TLS/proxy acceptance.
After restart, login and persistence of the voided credit and completed
reconciliation also passed.
Fresh Trivy scan: **zero HIGH/CRITICAL vulnerabilities**, including unfixed
advisories. The earlier 359-request sweep is separate, older evidence.
A CycloneDX 1.7 SBOM records 168 image components. Runtime and development
requirements both pass fresh strict dependency audits.

## Static-analysis dispositions

Local official CodeQL CLI 2.27.0 analyzed Python and JavaScript, with query
packs `codeql/python-queries@1.8.10` and `codeql/javascript-queries@2.4.5`.
Both the default code-scanning suites and the broader security-and-quality
suites completed locally. Default suites: **15 Python, 0 JavaScript findings**;
expanded suites: **401 Python, 11 JavaScript findings**. Analysis covered all
727 Python and 104 JavaScript/TypeScript files selected by the extractors,
plus five workflow files in each language run. Findings are not suppressed
or uploaded to GitHub. These are raw alert counts, not confirmed bug counts.

Security-path review:

- Eleven path-injection alerts concern backup restore, OCR intake lookup and
  receipt attachment. Resolved containment checks guard filesystem access;
  intake identifiers must be 32 hex characters; sidecar metadata constrains
  stored filenames; attachment entity types are schema-constrained and entity
  IDs are resolved against database rows. No bypass was reproduced. These are
  reviewed scanner candidates, not a penetration-test result or protection
  against an already-compromised process modifying files concurrently.
- The FX partial-SSRF alert uses a fixed HTTPS Bank of Canada origin; currency
  strings occupy the series path, not the destination authority. No arbitrary
  host injection was reproduced. No real external provider request was made.
- Four other default-suite alerts are test-only: three substring checks assert
  mocked/constructed provider URLs, not production destination validation; one
  local HTTPServer is wrapped in a server TLS context before serving. Together
  with the eleven filesystem alerts above, this accounts for all fifteen
  default Python findings.
- Remaining log alerts in company/QBO paths use constrained database/file
  identifiers, entity allowlists or escaped names. Safe-error alerts persist
  because the scanner still follows taint through `%r`; the new CR/LF tests
  verify the encoding behavior. No blanket logging suppression was added.
- The reported AI wrong-argument call resolves a zero-argument test double;
  production dispatch accepts tool parameters. The two migration uninitialized
  locals are assigned in their respective loops before use. These were checked
  in source, not fixed by disabling rules.
- Expanded JavaScript findings are eight unused locals, one overwritten local
  and two Jinja percent-format expressions misread as JavaScript conversion.
  Python expanded findings also include unused test globals, assert side
  effects, import cycles, empty exception handlers and resource management.
  These remain maintainability findings; this review does not certify every
  empty handler or import cycle as harmless.

Bandit: **0 high, 6 medium, 45 low**. Medium findings were inspected: a report
helper named `extra` is not Django SQL; `0.0.0.0` occurs in a blocked-host set;
blind-index/encryption identifiers come from registered model metadata;
schema-repair identifiers come from inspected/pending migration tables; FX
requests use the fixed HTTPS origin above. No public SQL-injection or binding
issue was reproduced. No new exclusions were added.

Gitleaks scanned the tracked plus nonignored untracked source snapshot,
excluding ignored local credentials/data: **3 findings**, each an explicit
synthetic secret in AI/template regression fixtures. No real credential was
identified in that scope. The redacted report is retained; this is not an
audit of ignored local files or all historical Git objects.

## Typing debt, not a clean type check

Pyright with the actual `.venv/bin/python` interpreter reports **1,888 errors
in 333 files**: 995 argument, 417 general type, 357 attribute, 46 return and
73 other diagnostics. Fifteen missing imports refer to optional platform OCR
dependencies. ORM `Column`/instance annotation mismatches dominate, but it is
incorrect to dismiss the entire set as harmless ORM noise. Optional-value and
other contract diagnostics remain a separately scoped remediation backlog.
Pyright is not configured as a CI gate. The earlier 1,830 count is historical;
an invocation with the wrong interpreter also produced misleading missing
dependency noise and is not the baseline used here.

## Evidence and limits

Risk-focused review covered account graph mutation, monetary/schema guards,
payment ownership, transfer/reconciliation locking, error responses/logging,
OCR/backup path access, schema-repair boundaries and scanner-reported sinks.
Earlier accumulated review is linked from the validation record. Automated
tests and this targeted review do not constitute a fresh line-by-line review
of every changed/untracked file. Browser interaction remains blocked by the
unconnected Chrome surface; native packaging, real provider credentials,
contributor-term acceptance and deployment capacity remain separate gates.

Evidence is archived outside the repository at
`/home/aitest/slowbooks-validation-20260920-vi7IeD/`, including redacted secret
scan results, SARIF, the image SBOM and the tested dependency/toolchain versions.
Disposable test containers, synthetic PostgreSQL data and the internal network
were removed; the final image and evidence remain. No existing service was stopped.
Original local paths:

- `/tmp/slowbooks-final-fixes-pg-20260920.log`
- `/tmp/slowbooks-final-live-20260920.json` and matching `.py` probe
- `/tmp/slowbooks-final-trivy-20260920.json`
- `/tmp/slowbooks-codeql-skn23e/` (databases, logs and SARIF)
- `/tmp/slowbooks-pyright-final-review-20260920.json`
- `/tmp/slowbooks-bandit-final-review-20260920.json`
- `/tmp/slowbooks-final-gitleaks-20260920.json` (redacted)
- `/tmp/slowbooks-final-source-manifest-20260920.sha256`
