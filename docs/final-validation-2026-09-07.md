# Final validation — 2026-09-08

Release-candidate validation ledger for
`claude/main-branch-protection-2tqh90`. It covers the current local working tree,
including uncommitted changes. This is test evidence, not a compliance
certification or a substitute for signed-platform, legal, tax, penetration, or
live-provider acceptance.

## Exit criteria

The final full-suite run includes the concurrent-accounting and audit fixes.
Its before/after source fingerprints match. Local engineering validation is
complete; the public-release acceptance limitations below remain open.

- [x] Performance/query regression gate passed on the final source snapshot.
- [x] A new user followed the public Docker path from a clean source copy.
- [x] Fresh setup, authentication, navigation, representative bookkeeping and
      HR flows, restart, and persistence worked without recovery steps.
- [x] Exposure, transport defaults, secrets, migrations, backups, dependencies,
      and container confinement were checked.
- [x] Full regression suite and updated-image checks pass after the final
      concurrent-accounting fix.
- [x] Findings were fixed and retested or recorded below as release limitations.

## Validated snapshot and environment

- Git HEAD: `c8b71a8da8e9331bc151d36f705c8515a9ae3f21`, plus the uncommitted changes
  described by this report.
- Final candidate fingerprint (identical before and after the full suite):
  `7b4280937cb8db2674769b3bf2ffdc09d8e18aecc685d88edd7c27874063f858`.
  This hashes sorted unique tracked/untracked candidate paths and contents,
  excluding Markdown so this evidence ledger can be finalized afterward.
- Debian 13, Linux 6.12.107, Python 3.13.5, Docker 29.8.0, Compose 5.5.1,
  Node 22 for the matching CI frontend/syntax checks (also checked with Node
  25.5.0), and Chrome 152.0.7977.82 for the earlier browser walkthrough.
- PostgreSQL ran in isolated Docker volumes with synthetic data and disposable
  test secrets. No customer data or live financial/provider credentials were used.
- Database migration revision: `fb23cd45ef67 (head)`.

## Results

### Regression, formatting, and performance

- Final run: **3,232 passed, 10 skipped, 0 failed**, with 99 warnings, in
  **18m51s**. Coverage was **82.35%** (22,246 of 27,013 statements;
  4,767 missed). The candidate fingerprint was unchanged before and after.
  Local runner: `/tmp/slowbooks-remote-final-gate-20260908.sh`; full output:
  `/tmp/slowbooks-remote-final-ci-20260908.log`.
- The 10 skips are three intentional public-route authentication exclusions and
  seven host-only OCR skips. The same OCR modules ran in the production image
  with Tesseract 5.5.0 and Poppler 25.03.0: **42 passed, 0 skipped**.
- N+1/query gate: **18 passed**; analytics used 10 SELECTs and every endpoint
  remained within its query bound.
- Black checked 489 files, Ruff passed, every application/Cloudflare JavaScript
  file parsed, the 10 frontend refresh tests passed, and `git diff --check` passed.
- The suite reported non-failing library/tooling warnings, including Python 3.13
  source-analysis warnings and five unclosed SQLite connection warnings. A strict
  isolated Xero run did not reproduce them. They are not represented as zero.

### Clean Docker install and new-user walkthrough

- A clean source copy built successfully with a 1.18 MB build context. Compose
  created PostgreSQL, ran migrations, and started SlowBooks without manual volume
  repair.
- First setup rejected a short password, accepted a valid administrator, rejected
  repeat setup, and denied anonymous customer access.
- The walkthrough created a customer and a $250 invoice, marked it sent, recorded
  payment, and immediately showed a zero balance. Employee onboarding completion
  updated in-place and persisted as 1/8 (12.5%).
- A container restart retained the session, accounting records, and onboarding
  state. A real backup was created (399,479 bytes).
- Invoice PDF generation returned a one-page tagged PDF. A real OCR upload returned
  HTTP 200 and extracted the fixture date and total.
- Analytics loaded, and Settings exposed all eight AI provider choices, editable
  model identifiers, Cloudflare/self-hosted configuration, and the custom
  OpenAI-compatible endpoint path.

### Security and operations

- `pip check` found no broken requirements. Strict `pip-audit` found **no known
  vulnerabilities** in `requirements.txt`.
- Bandit found **0 high**, 5 medium, and 39 low findings across 50,085 lines. The
  medium findings were reviewed: a SQLAlchemy `.extra` identifier false match;
  the AI SSRF blocked-address literal; two dynamic SQL paths constrained by
  internal model/field registries; and a fixed HTTPS Bank of Canada URL.
- Development and production Compose configurations rendered with required
  secrets. Kubernetes manifests parsed and passed all 20 manifest tests.
- The application ran as UID/GID 1000 with a read-only root filesystem,
  `cap_drop: ALL`, `no-new-privileges`, an init process, and writable dedicated
  upload/backup volumes. A write probe under `/app` was refused.
- The host publication was loopback-only. `/health` returned HTTP 200 and the
  authenticated accounts, customers, backups, and OCR status APIs returned 200.
  The root response included CSP, `nosniff`, frame denial, referrer, and
  permissions-policy headers.
- Secret, conflict-marker, ignored/tracked-artifact, manifest, and local Markdown
  link checks passed. Repository-generated test/cache output remains ignored.

### Owner-main preservation

`origin/main` is an ancestor of this branch (`0` commits behind at validation
time). The latest 10 main commits were inspected individually, covering the
saved-report label, macOS staple target, Black formatting, Defender guidance,
nonprofit terminology, v2.9.1 cleanup, and custom-AI wording. All 185 paths
touched by those commits still exist. The most sensitive implementation files
(`reports.js`, `packaging/macos/release.py`, and its test) matched main byte for
byte, and the remaining behaviors are present in source and regression tests.

## Findings fixed during this validation

- Made Docker persistent-volume ownership deterministic while keeping the app
  container non-root; added read-only roots, dropped capabilities, and bounded
  temporary storage for Compose/Kubernetes.
- Required stable session, settings-encryption, audit-signing, and database
  secrets; corrected Kubernetes secret instructions so one generated database
  password is used consistently by PostgreSQL and `DATABASE_URL`.
- Removed a stale dependency-audit waiver after upgrading to the fixed
  WeasyPrint release.
- Fixed stale onboarding/background refresh paths and added frontend regression
  coverage for all related create/update/delete flows.
- Fixed sales-tax payment date validation and searched equivalent date fields.
- Updated AI provider/model configuration, custom endpoint backend wiring,
  SSRF/TLS wording, and Settings copy so every offered provider path is named.
- Repaired migration/schema-parity and stale payroll fixtures, tightened backup,
  attachment, session, proxy/TLS, and audit-sensitive-value handling, and added
  focused regression tests.

## Release limitations

- This is **not** unconditional enterprise, accessibility, HIPAA, tax, or legal
  certification. HIPAA documentation describes technical readiness and operator
  responsibilities, not an attestation.
- A refined static accessibility scan found 564 label candidates without a
  `for` or an enclosed control across 50 JavaScript files (36 other labels
  correctly enclose controls; six use explicit `for`). These are source-level
  candidates, not a rendered WCAG finding count. The earlier browser tree also
  exposed unnamed form fields. Remediation and keyboard/screen-reader testing
  remain a public-release gate; see [accessibility](accessibility.md).
- Real payroll remains blocked until each used state/local table, paid-leave cap,
  and e-file layout is independently verified; see [working notes](todo.md).
- No external penetration test, real Kubernetes cluster/ingress/TLS deployment,
  or live paid AI, bank, payment, payroll, or e-file provider was exercised.
- Native signed Windows/macOS packaging and runtime tests require those platforms.
  Source-level packaging tests passed on Debian.
- Hosted GitHub Actions and CodeQL still need to run on the eventual pushed commit.
- Source still reports version 2.9.3 while 2.9.4 is Unreleased. The version bump,
  release notes finalization, tag, and signed artifacts belong to the release step.
- Existing deployments need the [concurrency-fix upgrade checks](operations.md#concurrency-fix-upgrade-checks).
  These fixes do not automatically repair pre-existing balance drift or rehash
  broken historical document-audit chains.

## Verdict

**LOCAL ENGINEERING CHECKS PASS — ready for review, not public enterprise
release approval.** Accessibility, workload/capacity acceptance, and deployment
limitations remain open. Passing the engineering checks does not clear those
gates. This records pre-commit local evidence; hosted CI and code-owner review
remain required before merging through the repository's pull-request process.

## Remote-session follow-up — 2026-09-08

- Paused the original VS Code agent to prevent simultaneous edits; preserved
  its full-suite process and continued validation from the remote session.
- Reproduced a lost update on PostgreSQL: two simultaneous $10 journal entries
  persisted $20 of journal activity but only $10 in cached account balances.
  Journal creation and invoice rebuild/reversal now lock affected accounts in
  ID order and refresh cached ORM balances. Pending work is flushed before
  refresh so repeated journals within one transaction remain correct.
- The regression failed before the fix and passed afterward. An expanded
  eight-writer/80-journal test also passed with exact balances; the 58 focused
  accounting, invoice, contractor, invariant, and query tests passed.
- The same lost-update regression also failed on file-backed SQLite, where
  `FOR UPDATE` is ignored. Account locking now starts `BEGIN IMMEDIATE` when
  SQLite has not yet opened its write transaction. The shared regression matrix
  exercises both databases with two single-entry writers and eight writers
  posting ten journals each, including previously cached account objects.
- Further concurrent-write review reproduced audit-chain forks on both empty
  and existing PostgreSQL chains. A transaction-scoped PostgreSQL advisory lock
  now serializes the read-and-append sequence; SQLite reserves its write
  transaction before reading the tip. E-signature audit creation now defers
  commit to the envelope update, so a failed signature rolls both records back.
  The in-progress second full run was stopped at 64% to validate these changes
  on a new frozen snapshot rather than mixing revisions in one claimed result.
- All 67 focused accounting/audit/signing/checkpoint tests passed, including
  PostgreSQL and file-backed SQLite chain concurrency and signature rollback.
- After extending account serialization to SQLite, all 88 focused tests passed.
  The final full-suite run collected 3,242 cases: 3,232 passed and 10 skipped.
- Rebuilt the final source into image
  `sha256:38c288b6cee6faf6521aa44032bca6bd58a700f8d0a0b60ba9d005cda54ae228`;
  Compose startup and health checks passed with persistent data intact.
- On the preceding image, before the final SQLite-only locking change, eight
  simultaneous PostgreSQL-backed HTTP writers created eight unique invoices
  and eight payments, with no errors. All invoices were paid; A/R net change
  was $0, undeposited funds increased $80, and revenue increased $80 exactly.
- On that preceding image, four simultaneous synthetic portal-sign requests signed three distinct test
  documents and rejected the duplicate with HTTP 400. Every signature hash and
  the complete document-audit chain verified afterward. These were explicitly
  noncontractual synthetic fixtures, not real employee agreements.
- On the final image, authenticated navigation, customer/invoice creation,
  invoice editing, full payment, PDF generation, and anonymous-access rejection
  passed HTTP/API smoke checks.
- Browser automation could not reconnect in this remote session because its
  installed bridge referenced a missing plugin module. The earlier browser
  walkthrough is retained as historical evidence; current-image verification
  above is HTTP/API acceptance, not a new visual or screen-reader assessment.
- Rechecked OCR in an isolated production-image container: 42 passed, no skips.
- Rechecked dependency integrity and strict vulnerability audit: no conflicts
  and no known vulnerabilities. Bandit: zero high, five reviewed medium, 39 low.
- Exercised the production backup and restore service against a newly created
  disposable database. All 96 compared tables (129 rows) matched by row count
  and complete-row hash after restoration of a 399,745-byte backup. The backup
  registry is excluded because its new row is written after the dump. The
  scratch restore database was dropped afterward; the source remained intact.
- Seeded a separate disposable PostgreSQL schema with 1,000 customers, 50,000
  invoices, and 150,000 lines. All 192 full-page reads returned the expected
  500 invoices and three lines per invoice; each page used two SELECTs.

| Concurrent readers | Reads | Errors | Pages/second | Median | p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 64 | 0 | 5.98 | 164 ms | 229 ms |
| 8 | 64 | 0 | 5.82 | 1,328 ms | 1,719 ms |
| 32 | 64 | 0 | 5.06 | 4,316 ms | 6,639 ms |

This is a bounded in-process route/ORM workload on the shared validation host,
not an HTTP/TLS, multi-worker, sustained-soak, or capacity certification. The
latency at 32 readers must not be presented as enterprise capacity acceptance.
Deployment sizing needs an agreed workload and latency/error budget. The
synthetic load schema was removed after the run.
