# SlowBooks continued beta validation October 5 2026

The continued beta closes the first audit's stale payroll draft and ordinary
taxable employer-contribution defects, plus unpaid-period and repeated
retro-adjustment defects found during independent review. The final complete
regression passed: 6,547 tests, 12 documented conditional skips, zero
failures and 96.92% statement coverage. No commit, push or PR has been
created. Public payroll release remains gated by the limitations below.

## Payroll contracts

New drafts retain an immutable paid-history baseline. Payroll creation,
processing and cancellation serialize writes per employee. If another check
changes that baseline, processing returns 409 without modifying or posting
the draft. Cancel and recreate it to calculate against the new paid history.
Cancellation marks the run void, refunds exact recorded benefit/loan
reservations, and releases its linked time entries. Paid runs, repeated
cancellation and unverifiable legacy reservations are refused.

An actual PostgreSQL beta case starts with $184,000 paid Social Security wages
and two $1,000 drafts withholding $31 each. The first processes; the second is
held. Its cancelled replacement withholds $0, preserving the correct combined
$31 rather than posting $62. Concurrent PostgreSQL and SQLite tests exercise
the same serialization contract, including an independent negative control
that fails when the employee lock is removed.

Employer contributions require explicit `fully_taxable` classification for
the supported ordinary noncash case. On $2,000 cash pay, a $100 contribution
produces $2,100 tax wages, federal withholding $168.15, Social Security
$130.20, Medicare $30.45, and cash net $1,671.20. The journal separately debits
$2,000 wages and $100 benefit expense and balances. W-2 and Form 941 wages use
the saved contribution classification; changing the current code does not
reinterpret the paid paycheck. The paystub identifies the $100 noncash amount
without adding it to cash earnings. The actual one-page PDF was rendered and
visually inspected.

Migration `b7fringe2026105`, after `m3heads2026105`, adds nullable
`benefit_codes.employer_tax_treatment` without updating existing records.
Legacy taxable flags, including seeded group-term life insurance, remain
unclassified. New positive unclassified taxable employer contributions return
422. This mode
requires the owner to establish that the entire contribution is ordinary
taxable value across all modeled wage bases; employer cost does not establish
that value. See [IRS Publication 15-B](https://www.irs.gov/publications/p15b).

Retro pay uses processed regular earnings from eligible work periods. Work
completed before the raise is excluded even when its check was paid later.
A period spanning the effective date requires reconciliation when the source
cannot establish the post-raise hours. Pending and processed adjustments claim
their original paid run IDs; another adjustment claiming those periods returns
409. Cancelling an unpaid adjustment permits restaging. A later raise on
distinct paid periods remains supported; overlapping subsequent raises require
explicit reconciliation of the amount already paid.

New regular stubs snapshot their earnings source and salary frequency. Explicit
gross overrides do not generate rate-based arrears. Repricing retains fixed
reported/paycheck tips and the original paid gross floor for recorded tip
top-ups. Unmarked legacy earnings, prorated salary without a verified split,
and a change between hourly and annual salary units are held for review.
The legacy refusal also holds otherwise legitimate old records whose source
cannot be proven; it does not silently infer their pricing. Applying retro pay
updates the employee's current rate. Cancelling its payout leaves that rate
change in place. Retro/PTO earnings metadata is excluded from the paystub's
employee deductions so printed totals match actual withholding and net.

## Verification scope

The complete regression finished in 29m 51.63s, including all 47
Chromium cases, native OCR and the PostgreSQL contracts. It used a frozen
1,157-file application, test and configuration manifest, SHA256
`1ce05a30e3ae858dd00b62c758945f81060a04891e1c00088bee7a13c2eca428`.
The build's before/after manifest matches it exactly. The final image is
`slowbooks-qa:20261005-retro-fringe-patched`, OCI index
`sha256:055c9a4e7571f5204a375f72e6bb9efd855a274ec70057e0d5cf86e2766d06ed`;
its amd64 manifest is
`sha256:2d357158de795c61939c30ad6f8a78f717f85392600c95f38dcc7827a306ccc8`
and configuration is
`sha256:6ba1d0a06cdb7cba51957e9a0628f2441a9b152b0d2a4e8f9a025cefffcbc291`.
All 556 checked application, migration, script and build files match the
running image. Their canonical path/hash manifest SHA256 is
`f3672fc21bf3cb6ec5d22a1e09831bf4db419d2e1550d192029ac76db9a615ce`.
Documentation is updated separately and excluded from those source manifests.

| Area | Status | Current evidence and scope |
| --- | --- | --- |
| Complete regression and coverage | Pass | Entire `tests/` collection: 6,547 passed, 12 conditional skips, zero failures/errors; 96.92% statement coverage; all 47 browser cases, native OCR and both PostgreSQL contracts enabled. Frozen source unchanged through completion. |
| Payroll regressions and concurrency | Pass | 151 focused cases, including 18 actual PostgreSQL/SQLite concurrency variants. Independent old-service and lock-removal controls fail as expected. Counts overlap the complete regression. |
| Payroll on actual PostgreSQL image | Pass | 37 fringe/cap/cancellation and 25 retro HTTP checks. Correct wages/net, balanced posting, immutable reports, exact reservation refunds, duplicate claims held, cancelled claims restaged and distinct later periods allowed. |
| API inventory sweep | Pass within scope | 617 operations on 488 paths; 295 GET probes, zero 5xx/transport failures. Responses: 249 successful, 43 absent-record 404s, two expected 400s and one redirect. Nineteen provider/token/file variants excluded; this is not acceptance of every operation. |
| Frontend contracts | Pass within scope | Persistent browser cases and independent checks cover classification, cancellation, readonly page/server gates, actual stale-history guidance and both themes. Earlier Node/controller checks remain 85 passed; browser/source provenance is retained. |
| PDFs and image native tools | Pass | Both changed one-page paystubs rendered and visually inspected with correct earnings/deductions/net. Final-image Poppler/Tesseract recognized the synthetic paid invoice's $51.06 total. PDF/UA acceptance remains open. |
| Backup and recovery | Pass | Actual-image backup restored to separate `qa_restore_continuation`; complete-row hashes match 101 tables and 1,518 rows. Only the new backup registry row and its post-dump INSERT audit excluded. |
| Restart persistence | Pass | Login, paid invoice, encrypted ACH masking/reveal, backup registry, new fringe net/snapshot, paid retro adjustments and balanced trial balance survived restart. |
| Strict HTTPS and runtime hardening | Pass in QA | Private CA verified, 308 redirect/HSTS, Secure/HttpOnly/SameSite cookies, shared Redis throttling, two observed workers, PostgreSQL TLS 1.3, nonroot/read-only/capability-free workers. |
| Kubernetes | Pass in QA | Exact final configuration bound to OCI archive and kind import; app ready with zero restarts, b7 migration no-op, six Python/three served static hashes match, TLS 1.3/Redis and six allowed/blocked network probes pass. All six observed app-derived containers use the patched config; disposable probes subsequently removed. |
| Dependencies and image | Pass with supporting-image gate | Final app has zero known vulnerability/secret findings, 168-component SBOM and 70 audited Python distributions. Supporting release images retain the gates below. |
| Syntax, formatting and source security | Pass or reviewed as named | 1,089 syntax checks, Black/Ruff/diff checks, 31 documentation/release guards; nonzero security/type findings retain their dispositions in the next section. |
| Hosted checks | Earlier commit passed | Online recheck confirms CI success for `1a5d90f`; it does not certify this uncommitted tree. |
| External and human acceptance | Open | Native signed platforms, designated providers, jurisdiction approval, human accessibility, sustained capacity, independent security and owner review remain required. |

The 12 skips comprise four intentionally public authentication routes, five
SQLite variants whose actual PostgreSQL row-lock counterparts passed, two
control accounts created on demand instead of seeded, and one empty frontend
parameter collection. Separate fixtures for both on-demand accounts passed;
these two supplemental cases are not added to the full-suite total. All ten
warnings reported in pytest's summary are unclosed SQLite connection
`ResourceWarning` messages. The log separately retains invalid-decimal
`SyntaxWarning` output.
Coverage is 34,182 of 35,267 statements, with 1,085 missing and 14 excluded.

Earlier completed results remain in the
[first beta checklist](beta-readiness-2026-10-05.md), including broad accounting,
portal, browser/accessibility, nonprofit and capacity lanes. Those observations
retain their original build provenance and are not relabeled as new-image
executions. Independent lane counts overlap and must not be summed as unique
test cases.

The Kubernetes migration-first predecessor proof upgraded m3 to b7 while
preserving 77 rows across ten financial tables. The final refresh repeated b7
as a no-op and preserved the same paid invoice, 56 accounts and balanced books.
Those Kubernetes benefit tables were empty; populated legacy snapshot/flag
preservation is proved by separate migration fixtures. A further refresh
updated the PostgreSQL certificate initializer and disposable probes to the
same patched app config. The four persistent/completed app-derived usages
match; both probes were removed after their checks. Supporting deployments,
PVCs and secret identity/content hashes were preserved. Historical app
ReplicaSets have zero desired/current replicas and retain old metadata.
PostgreSQL/Redis main support images retain their separate provenance; the
clean final app scan does not cover every cluster image.

## Security review

The final continuation source audit captures 596 production files, with
manifest SHA256
`9c32ec9b575b9c129de4f2930f2e1793039c636e9ced28860feffa0e26b868e8`.
The changed Python was freshly analyzed after the retro corrections and
checked unchanged afterward. CodeQL records the same 11 Python default
alerts and 483 expanded results. The two additions compared with the first
completed audit are test-only empty-except warnings: concurrency barrier
timeouts deliberately let the first serialized draft or retro operation
proceed. No production security alert was added or suppressed. JavaScript
retains zero default alerts and nine expanded results; a 190-file byte
comparison verifies unchanged JavaScript, HTML, configuration, CSS and shell
inputs from the first continuation scan.

Bandit retains seven medium and 46 low findings, with no high findings.
Gitleaks retains four synthetic test-fixture hits. Source Trivy records zero
dependency vulnerabilities and 18 low/one medium configuration findings.
Existing dispositions remain recorded rather than treating those scanners as
zero-alert passes. Pyright reports 1,988 errors across 353 application files,
19 more than the first completed audit and seven more than the earlier
continuation snapshot. The added diagnostics concern ORM `Column` inference
and control-flow narrowing; static typing debt remains. Black, Ruff,
1,089 syntax checks and 31 documentation/release source guards passed.
Actionlint and ShellCheck results retain byte-identical inputs; fresh
`pip check` passes and all 110 local installed distributions match their
previously audited versions.

The first continuation app image, OCI index
`e5e55e731c5983a07bc8bb3591572562e462a38150fecbba8b3e16c5b7a13b00`,
regressed from Alpine 3.24.2 to 3.24.1 and reverted ten OS package versions.
Fresh Trivy found three fixable OS advisories and zero secrets:

| Installed package | Finding | Patched version |
| --- | --- | --- |
| libexpat 2.8.4-r0 | High, [CVE-2026-93990](https://blog.hartwork.org/posts/expat-2-8-5-released/) | 2.8.5-r0 |
| pcre2 10.48-r0 | High, [CVE-2026-103111](https://github.com/PCRE2Project/pcre2/security/advisories/GHSA-r9hj-j2rw-4q3m) | 10.49-r0 |
| libpng 1.6.58-r1 | Scanner unknown; [upstream moderate, CVE-2026-46675](https://github.com/pnggroup/libpng/security/advisories/GHSA-qvg3-h654-xq3j) | 1.6.59-r0 |

An isolated disposable container first proved all three repairs available
with TLS verification enabled. The final image was then rebuilt with a fresh
base and uncached APK/dependency layers. Its OCI index is
`055c9a4e7571f5204a375f72e6bb9efd855a274ec70057e0d5cf86e2766d06ed`,
under tag `slowbooks-qa:20261005-retro-fringe-patched`. Independent archive
inspection records its platform manifest and actual configuration digest.
It restores Alpine 3.24.2 and all ten regressed package versions, including
the three patched libraries above. The final current-database Trivy scan
records zero known vulnerabilities and zero detected secrets. The vulnerable
predecessor scan and descriptor chain remain separately archived.

The rebuilt image's actual 70 installed Python distributions were freshly
enumerated and independently audited as exact pins: zero known advisories
and no skipped distributions. Their versions match the predecessor image;
eight differ from the local test environment, so image runtime acceptance
retains separate evidence. The SBOM contains 168 components.
`security/final-python/source-security-final-summary.json` and
`security/image-security-final-summary.json` record the final source and
image results. Continuation `security/` also retains scanner dispositions,
the unchanged-input proof, image descriptor chain, package comparisons and
repair probe. The original audit results are unchanged.

## Remaining release gates

- Legacy/imported checks without benefit snapshots and historical incorrect
  withholding require reconciliation and possible amendments. Existing Form 941
  line-7 adjustments do not establish that non-rounding discrepancies are valid.
  Legacy drafts
  with missing history or unverifiable positive reservations are held. Legacy
  retro earnings, partial/prorated periods, pay-type changes and subsequent
  overlapping raises require verified allocation or reconciliation.
- Special fringe valuation/exclusions, group-term life insurance, taxable
  post-tax matches, employer-paid employee-tax gross-ups and insufficient
  cash remain unsupported. Ordinary classification requires owner approval
  of the tax treatment and value.
- State employer-size tiers, exemptions, equivalent plans and localization;
  simplified state/local withholding; legacy SUI wage approximations and
  local W-2 box 18 require deployment-specific verification. SUI state filters
  still use the employee's current work state, so historical state moves need
  review. Complete EFW2, Publication 1220 and official e-file acceptance remain
  open.
- Stock supporting release-image updates, reviewed nonzero static scanner
  findings and ORM typing debt remain open. A clean QA derivative does not
  certify repository support-image defaults.
- Signed Windows/macOS install/upgrade, designated provider sandboxes, public
  TLS/ingress, human assistive technology/PDF-UA review, sustained capacity
  and independent security review remain required.
- Final hosted CI and merge-reference checks, code-owner review, contributor
  terms and author signoffs remain required. Earlier hosted CI tested the
  committed starting tree, not these local changes.

## Evidence

Release builds need a refreshed base and package layer (`--pull --no-cache`)
and a scan of the exact resulting image digest. The first continuation build
reused an older APK layer despite the Dockerfile's upgrade command; the final
build refreshed it. The environment-specific build file mounts the session CA
only during network steps, preserves TLS verification and leaves the
repository Dockerfile unchanged and does not add the session CA to the runtime
trust store.

New evidence is retained outside Git in
`/home/aitest/slowbooks-validation-20261005-continuation-QivGHp/`. The original
`/home/aitest/slowbooks-validation-20261005-NoP66g/` evidence remains unchanged.
Logs retain before-fix reproductions, failed harness attempts and the stopped
interim regression separately from completed final results. Generated QA
environment files, certificate keys, payroll details and raw backups are
private and must be excluded from publication.

`validation-index.json` records the final full-suite summary, artifact hashes,
source/image provenance, documentation hashes and scoped QA cleanup. The
complete result is in `backend/unified-summary.json`; runtime lane references
are in `runtime/runtime-lane-index.json`.

The synthetic beta remains at `http://127.0.0.1:33105`; its generated login is
in the original evidence directory's `runtime/beta-login.txt` (mode 0600).
Only authorized QA stacks and fixtures were changed; the repository's real
environment, keys, customer files and unrelated Docker services were preserved.
