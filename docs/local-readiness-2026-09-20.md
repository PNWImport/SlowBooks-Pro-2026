# Local readiness checklist — September 20, 2026

> **Note (2026-10-05):** This file is a historical record of the pre-intake branch state and is kept as written. The branch has since absorbed upstream 2.19.0, with Alembic migration head `m3heads2026105` and a fresh full-suite run of 6,187 passed / 46 skipped.

Local review only: no PR, issue, workflow dispatch, commit, push or merge.
This checklist mirrors the repository's GitHub checks without claiming a
hosted run. Target: 2.17.0 unreleased, upstream content through `a1022f8`
(upstream release 2.16.1).

## Automated checks

- [x] Final full Linux execution: 4,859 passed, 11 skipped, one runner-related
  parent-watcher failure. The exited child remained a zombie under PID 1
  without a reaper; all 47 launcher/desktop tests pass with `tini -s`.
  Original failure log retained. Snapshot statement coverage 97.34%; this is
  not a zero-failure full-run label or coverage of later source edits.
- [x] Fixed concurrent import replay on PostgreSQL/SQLite and duplicate SQLite
  reconciliation starts. 27 focused accounting/replay tests and 23 related
  banking tests pass (five deliberate SQLite-variant skips). Latest image and
  live persistence/import checks pass; Trivy reports zero vulnerabilities.
- [x] Refreshed source scans: CodeQL 15 Python / 0 JS; Bandit 0 high / 6 medium /
  45 low; three synthetic Gitleaks fixtures. Pyright stays at 1,888 diagnostics.
  These are reviewed executions, not blanket zero-alert passes.
- [x] Black: 732 Python files clean; Ruff and `git diff --check` pass.
- [x] Latest intake: 57 importer tests plus seven replay/opening-balance tests
  pass; 32 frontend tests pass. Black now checks 732 files; Ruff/whitespace pass.
  Rebuilt Linux app passes live Wave import/replay/refusal and existing invoice
  persistence checks. No new full-suite or concurrent-import certification.
- [x] Latest rebuilt-image Trivy vulnerability scan: zero findings across all
  severities; SBOM/EOL-metadata warnings retained in evidence. Fresh runtime,
  development and Linux-resolved desktop dependency audits also report zero
  known vulnerabilities; platform-conditional packages remain OS-specific.
- [x] Coverage-gap follow-up 4: 37 backup-route/service/error tests pass;
  backup routes reach 52/52 statements. Thirteen new cases cover download
  containment, error mapping and durable restore intent. Restore is stubbed
  in the new tests; SQLite resource warnings remain in the group output.
- [x] Coverage-gap follow-up 3: 39 payroll-boundary/Tier-2/gross-up tests pass,
  including ten new cases for invalid targets, missing records, cent-precise
  nonposting quotes and aggregate supplemental history wiring. No production
  changes or new whole-tree coverage claim.
- [x] Coverage-gap follow-up 2: 31 SQLite/PostgreSQL repair tests pass; repair
  now reaches **182/182 statements (100%)**, without exclusions. All 61 payroll,
  garnishment-remittance and job-costing tests pass, including posting rollback
  and missing-account guards. Ten additional regression cases; no additional
  production changes or new whole-tree coverage claim.
- [x] Coverage-gap follow-up: 63 migration/import tests (including PostgreSQL)
  and 35 payroll tests pass. IIF routes reach 97/97 statements; repair reaches
  175/182. Fixed repair retry dropping unowned empty tables; no coverage
  exclusions added. Earlier full-suite/image/scanner evidence predates this fix.
- [x] Workflow syntax: Actionlint passes; deployment scripts pass ShellCheck.
- [x] Dependency consistency (`pip check`), Git object integrity and one Alembic
  migration head (`ac14bd25ce36`) verified.
- [x] Full Linux coverage run: **4,780 passed, 12 skipped, zero failures,
  389 warnings**, exit 0, in 1,622.82 seconds (27m02s). Statement coverage:
  **97.04% (28,605/29,477)**; branch coverage was not collected. The final
  SQLite locking change was verified separately below, after this snapshot.
- [x] Focused upstream intake: 74 tests pass, including chart import,
  dashboard/report parity, permissions, terminology and version metadata.
- [x] Frontend controllers: all 32 Node tests pass; the upstream theme redraw
  probe also passes within the focused Python group.
- [x] Runtime and development `pip-audit --strict`: no known vulnerabilities.
- [x] Docker build and real PostgreSQL boot: version 2.17.0; restart, login and
  synthetic paid-invoice persistence pass.
- [x] Fresh PostgreSQL migration/parity, schema repair and accounting concurrency:
  **33 passed**, one warning, no skips (73.03 seconds).
- [x] Trivy HIGH/CRITICAL scan: zero findings, including unfixed advisories.
- [x] Linux CI-equivalent job with PostgreSQL 17, Python 3.13.15, native
  Tesseract/Poppler and an unprivileged pytest process. This was Debian Docker,
  not GitHub's Ubuntu runner. Twelve skips: four deliberate auth exemptions,
  five PostgreSQL-only cases' SQLite variants, two on-demand seed accounts and
  one Node-dependent theme probe. Both theme tests passed separately on the
  host; the 32-test frontend group also passed. No OCR/PG dependency skips.
- [ ] Windows pytest and skip budget: native runner required; upstream's
  budget of 78 is incorporated, not locally certified.
- [x] CodeQL Python/JavaScript analysis executed locally: default suites report
  15/0 findings; broader security-and-quality suites report 401/11. This marks
  execution, not a zero-alert pass; see the [dispositions](review-findings-2026-09-20.md).
- [x] Fresh Bandit triage: 0 high, 6 medium, 45 low. Gitleaks source snapshot:
  three synthetic test-secret findings, no real credential identified.
- [x] Post-review regression: 93 passed, two documented skips; includes real
  PostgreSQL and SQLite reciprocal-parent contention. Frontend remains 32/32 passing.

- [x] Import identity boundary follow-up: 47 focused tests pass; reject source
  references over 100 characters before posting instead of truncating replay
  lookups. The retained image now includes this edit: real PostgreSQL HTTP
  boundary/replay and persistence checks pass; refreshed Trivy reports zero
  known vulnerabilities. The full-run coverage snapshot still predates it.

## Live product checks

- [x] Fresh current-tree Linux Compose install: fresh volumes, automatic
  migration/57-account seed, healthy nonroot/read-only runtime; 35 accounting
  and 16 further HTTP requests pass. Real PDF, backup/download, restore into
  a separate database, restart/re-login persistence and native Tesseract/Poppler
  OCR pass. Synthetic stack retained on loopback port 33017. Browser control
  still unavailable; no visual acceptance or new image-CVE result claimed.
- [x] Isolated Docker HTTP run: 359 requests, zero 5xx; six additional successful
  GET checks cover valid date parameters, preferences, account detail and PDF.
- [x] Synthetic customer → invoice → payment; fractional-cent rejection;
  chart preview/apply and stale-plan rejection; nonprofit dashboard labels;
  YTD amount and balance-sheet identities.
- [x] Rebuilt final image: 35 more live HTTP checks pass for account hierarchy,
  vendor-credit application/reversal, transfers and completed reconciliation
  guards. Fresh image scan has zero HIGH/CRITICAL findings; see review evidence.
- [ ] Complete API workflow coverage: 574 operations inventoried; GET sweep
  exercised 274, of which 190 succeeded and 84 lacked fixtures or were rejected.
  The remaining 300 operations are not certified by that sweep. Selected write
  workflows above were tested separately; provider calls require their fixtures.
- [ ] Real Chrome navigation, rendering and interaction: browser tool returned
  no connected browsers and `Browser is not available: chrome`.

## Open issues and handoff

- [x] Reconcile ten new upstream commits and resolve the 2.16.0 version collision.
- [x] Correct earlier completion claims to distinguish fresh HTTP testing from
  historical browser evidence; see [validation](validation.md).
- [x] Inventory tracked changes and nonignored untracked files; scan that source
  snapshot for secrets. Risk-focused accumulated review found and fixed two
  additional defects with regression evidence in the review record.
- [ ] Review all intended files, including untracked application/test files,
  before any later commit. Nothing has been staged by this pass.
- [x] Triage Pyright categories using the correct virtualenv: 1,888 current
  diagnostics, superseding the historical 1,830 count. Predominantly ORM
  annotations, but other contracts remain; this is not a type-check pass.
- [ ] Remediate/accept remaining typing and expanded static-analysis debt.
- [ ] Owner decision on contributor terms; native signing, live providers,
  accessibility, payroll jurisdiction, penetration and capacity acceptance
  remain separate release requirements. Diagnostic-log privacy/access and
  retention also require deployment acceptance; log escaping is not redaction.

Evidence: [upstream reconciliation](upstream-reconciliation-2026-09-14.md),
[validation](validation.md), `/tmp/slowbooks-full-20260920.log`,
`/tmp/slowbooks-live-review-217-result.json`, and
`/tmp/slowbooks-trivy-20260920.json`. The final review artifacts are archived at
`/home/aitest/slowbooks-validation-20260920-vi7IeD/`; see
[review findings](review-findings-2026-09-20.md). They are local evidence,
not a hosted GitHub result or committed release attestation.
