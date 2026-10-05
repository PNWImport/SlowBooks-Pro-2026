# Local readiness checklist — September 26, 2026

Local review only: no PR, issue, workflow dispatch, commit, push or merge.
This checklist mirrors the repository's GitHub checks and the gates recorded
in [validation](validation.md) and the [September 20 checklist](local-readiness-2026-09-20.md),
without claiming a hosted run. Target: **2.18.0 unreleased**, upstream content
through `90ba2b7` (upstream release 2.17.3). Migration head `c7d1e4a92b30`.

## CI-equivalent

- [x] **GitHub CI workflow under `act` 0.2.89** (`pull_request` event,
  `catthehacker/ubuntu:act-24.04`, pinned action SHAs): **lint, test, pip-audit
  and docker-build jobs all succeed.** Test job: 4,952 passed, 16 skipped,
  **0 failed**, 133 warnings (down from an initial 407), in 42m26s. Two real
  CI-only defects found and fixed along the way: the parent-watcher test
  assumed a PID-1 reaper that `act`'s container doesn't provide (zombie
  children are exited, not merely signaled — fixed to check `/proc/<pid>/stat`
  for zombie state); `upload-artifact@v7` is rejected by `act`'s artifact
  server (nektos/act#6022/#6114) — that step is now skipped only under `act`
  (`if: ${{ always() && !env.ACT }}`) and still runs unconditionally on GitHub.
- [x] Full suite, 13 file-sharded processes (SQLite + PostgreSQL 17 migration
  database): 4,968 tests, 4,950 passed, 18 skipped, **0 failed, 0 errors**
  (rerun after the migration-head-pin fix; 16/16 migration tests). Sharded
  runs give no combined coverage figure; a separate coverage-enabled combined
  run measured **97.35% statement coverage**.
- [x] Focused reruns after later edits: invoice/payment/credit/bill 179 passed;
  AI + workflow-reading tests 272 passed; chart/analytics/theme 1,284 passed
  (2 documented skips); Kubernetes manifests 24 passed; schema-repair
  connection-leak fixes 15 passed, 2 skipped (PostgreSQL fixture unavailable).
- [x] Frontend: 32/32 (`node --test tests/frontend/*.test.cjs`, Node 24).
- [x] Black and Ruff over app, tests, scripts, packaging and migrations;
  `git diff --check` clean; `pytest --collect-only` 4,968 tests, no errors.
- [x] Test isolation and warning hygiene: tests no longer write into the real
  `app/static/uploads` (isolated via `SLOWBOOKS_DATA_DIR`); Pydantic money
  fields no longer serialize a bare `int` (151 model/schema defaults moved to
  `Decimal`); `reconciliation.completed_at` is timezone-aware; Alembic's
  `path_separator` config key updated (was the deprecated
  `version_path_separator`); Starlette's `TestClient` deprecation resolved by
  adding `httpx2` (provenance verified: pydantic org, by httpx's original
  author); legacy `Query.get()` replaced with `Session.get()`. A residual
  ~15-35 `ResourceWarning: unclosed database` in test fixture teardown is
  GC-timing-dependent (non-deterministic across identical reruns, not a
  regression) — 5 concrete leak sites fixed in `test_schema_repair.py`;
  further reduction is diminishing-returns cosmetic cleanup, not a defect.
- [x] Mechanical sweep: 74 JS/CJS files `node --check`; 22 YAML and 8 JSON
  files parse; shell `sh -n`; `compileall` over app, migrations, scripts,
  packaging.
- [x] Actionlint 1.7.12 on the upgraded workflows; ShellCheck (3 scripts).
- [x] `git fsck --no-dangling`; one Alembic head `c7d1e4a92b30`.
- [ ] Windows pytest lane and skip budget (≤ 78): native runner required.

## Security and supply chain

- [x] `pip-audit --strict`: runtime, development and desktop requirements —
  no known vulnerabilities (after the dependency refresh).
- [x] `pip check`: no broken requirements.
- [x] Trivy 0.74.0 (fresh DB) on the no-cache `slowbooks:2.18.0` image
  (Alpine 3.24.2, Python 3.13.15): **0 vulnerabilities at every severity,
  0 secrets**. CycloneDX SBOM: 168 components.
- [x] Trivy filesystem scan: 0 dependency vulnerabilities, no HIGH/CRITICAL
  license findings. Trivy config: Dockerfile and Compose clean; Kubernetes
  from 33 findings (5 HIGH) to 19 (0 HIGH, 1 MEDIUM false positive, 18 LOW
  accepted in `k8s/README.md`).
- [x] CodeQL CLI 2.27.1 (checksum verified): default suites **15 Python /
  0 JavaScript**, alert identities identical to the September 20 baseline
  (all dispositioned in [review findings](review-findings-2026-09-20.md)).
  Security-and-quality: Python 411 (+8 Alembic `revision` globals,
  +2 empty-except in a concurrency test), JavaScript 11 (unchanged).
- [x] Bandit: 0 high / 6 medium / 44 low (September 20: 0 / 6 / 45); the six
  mediums are the same reviewed findings.
- [x] Gitleaks (working tree and history): synthetic test fixtures only; the
  three `.env` hits are the git-ignored local secrets file, never committed.
- [x] Pyright: 1,889 errors (baseline 1,888); 13 new, all ORM-typing or
  guarded possibly-unbound in upstream's invoice-edit code; **0 new
  call-shape errors** (the one real one — `assert_not_reconciled` — was fixed).
- [x] GitHub Actions pinned to release commit SHAs; Dependabot configured for
  pip, Actions and Docker with the SQLAlchemy < 2.1 and ruff < 0.7 holds.
- [x] Cargo audit: not applicable (no Cargo manifest).

## Container and deployment

- [x] No-cache image build from current `python:3.13-alpine`: runs as uid 1000,
  pip module and launchers absent, Redis client, Tesseract, Poppler and
  PostgreSQL 17 client present; healthcheck accepts 200/307/308.
- [x] Fresh Compose install (new volumes): healthy, read-only root, all
  capabilities dropped, no-new-privileges; 57-account seed; setup (second
  setup refused); 401 before login; fractional-cent payment refused; paid
  invoice; PDF; OCR (Tesseract 5.5.2) reads 51.06 from the rendered invoice;
  backup created and downloaded.
- [x] Backup restored with `pg_restore` into a separate database: accounts,
  invoices, payments, ledger totals and migration head identical to live.
  (The PostgreSQL backup is custom-format despite its `.sql` name.)
- [x] Restart persistence: re-login, paid invoice and backup record survive.
- [x] Production Compose fails closed without `POSTGRES_USER`,
  `POSTGRES_PASSWORD` and `POSTGRES_DB`.
- [x] **Kubernetes on kind v0.33.0 (Kubernetes 1.37)**, following
  `k8s/README.md` verbatim: migrate Job completes over TLS; app, Postgres
  (uid 70, read-only root) and Redis Ready; in-cluster setup/login (Secure
  cookie, HSTS), 57 accounts, invoice posted, trial balance balanced; every
  app database connection TLS 1.3; NetworkPolicies enforced (ingress namespace
  reaches only the app; a stray pod reaches nothing); upgrade re-run of the
  migrate Job idempotent. Three deployment defects found and fixed on the way
  (bash in an Alpine image, Postgres without TLS, redirect-following probes).

## Live product

- [x] Upgrade of the September 20 PostgreSQL company (`ac14bd25ce36` →
  `c7d1e4a92b30`): 135 money columns widened, none left at precision 12;
  paid invoice preserved; trial balance balanced.
- [x] 28-step HTTP walkthrough on that upgraded company (see
  [validation](validation.md)): all pass after the invoice-edit fix.
- [x] API sweep: 580 operations; all 204 parameter-free GETs called on the
  fresh install — **0 5xx** (163×200, 31×422 needing parameters, 7×401
  portal/token routes).
- [x] Vocabulary walk (both company types): 2,305 / 2,311 strings,
  **0 source-backed code leaks**.
- [x] Version alignment: `__version__`, What's New and `/health` report 2.18.0;
  199 local Markdown links resolve.
- [ ] Real-browser (Chrome) acceptance: no browser available to this session.
- [ ] Live AI, SMTP, payment, bank-feed and OAuth providers: keys required.
- [ ] Real TLS proxy with a CA chain on a real domain (release-checklist §10).

## Platform-native and hosted

- [ ] Native signed Windows and macOS artifacts (windows.yml, macos.yml on
  `macos-15`); Windows Server Edition behaviour.
- [ ] Hosted GitHub CI and hosted CodeQL.

## Owner decisions carried forward

- [ ] Contributor terms / LICENSE 2.0 splash and installer terms.
- [ ] Accessibility, payroll-jurisdiction data review, penetration test,
  sustained capacity, diagnostic-log privacy/retention acceptance.
- [ ] Code-owner review of every modified and untracked path before commit.
- [ ] Remediate or accept typing and expanded static-analysis debt.
- [ ] SQLAlchemy 2.1 (psycopg 3) and ruff ≥ 0.7 migrations — deliberately held.
- [ ] GPT-6 Astra for Ask SlowBooks needs a Responses API adapter.
- [ ] Anthropic may retire `claude-haiku-4-5-20251001` from October 15, 2026.
- [ ] PR scope/split and a final upstream SHA recheck before opening it.

Evidence (local, not attestations): scratchpad gate logs and SARIF/SBOM/Trivy
JSON for this session; September 20 archive at
`/home/aitest/slowbooks-validation-20260920-vi7IeD/`.
