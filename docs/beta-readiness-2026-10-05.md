# SlowBooks beta validation October 5 2026

This is the first completed October 5 audit. Its source/image results and
then-open defects are retained as a historical snapshot. The
[continued beta validation](beta-continuation-2026-10-05.md) records subsequent
payroll corrections and their separate final verification.

The fresh local beta exercises the complete Linux application with SQLite,
PostgreSQL 17, Chromium, native OCR, Docker, and Kubernetes. The final regression
run passed 6,414 tests with zero failures and 12 documented conditional skips.
Statement coverage is 96.97%. Production payroll still has concrete processing
and state program gaps listed below. No commit, push, or PR was created.

## Repository and tested build

- Branch: `claude/main-branch-protection-2tqh90`.
- Starting commit: `1a5d90f2cd603662643f71a415f7881fe18a5e47`, plus the
  uncommitted corrections described below.
- Upstream main checked online:
  `71d10111f4c775e92834500a97d882a138f4c5a2`, already incorporated.
  The branch has 80 commits ahead and none behind that reference.
- Version: `2.19.0`; Alembic head: `m3heads2026105`; fresh seed: 56 accounts.
- Image: `slowbooks-qa:20261005-final`; image manifest:
  `sha256:23081c5872cea50b9dd0f84405586265baee63f68fe7385f8b9e6fa109fd70d1`.
  All 554 application, migration, script, and build files checked inside the
  running image match the frozen source; manifest hash:
  `f396787cf77c3070b89d62f3aeea5b1c98d60ce80fcdc499e1bfe1a1d9469df8`.
  The broader production source manifest covers 594 files and has SHA256
  `641411cbeb71d1aac3e43f261f7ecc667f0e42d5082ef49849fa3ffe283be245`.
  The complete regression's 1,150-file application/test/config manifest was
  identical before and after the run, SHA256
  `19d70261b2274714be595d9f798bee1ce6f1d957c0c4c503543246cdf3e11dee`.
- Local beta: `http://127.0.0.1:33105`, Compose project `sb-qa-20261005`.
  It contains synthetic acceptance records and generated QA credentials.

Broad HTTP, browser, portal and capacity lanes were captured on preceding
validated builds. The snapshot/tax-form HTTP lane ran on image `13a5f04f…`;
the current `23081c58…` build changes the shared notice stylesheet and its
existing regression fixture. Hash proof establishes unchanged production
Python, JavaScript and audited dependency versions between those two builds.
The current image has fresh notice, restart, recovery, HTTPS and Kubernetes
checks; the complete current-source pytest rerun passed all 6,414 executed
cases. Each lane retains its image/source provenance in the evidence.

Previously created SlowBooks test stacks, their volumes, and old test images
were removed as requested. This beta began with new volumes. The repository's
real environment file, encryption keys, and customer files were preserved.

## Program checklist

Pass means the named check passed in this environment. Reviewed means findings
remain with recorded dispositions. Open identifies a concrete release gate.
Independent checks overlap; their test counts must not be added together.

| Area | Status | Evidence and practical scope |
| --- | --- | --- |
| Complete Python regression and coverage | Pass | 6,414 passed, 12 conditional skips, zero failures/errors in 26m19s. All 43 Chromium cases passed; both PostgreSQL test contracts and native OCR enabled. Statement coverage: 33,902/34,962 = 96.97%, 1,060 missing and 14 excluded statements. |
| Frontend controller and combobox logic | Pass | 85 Node tests across both suites; browser rendering is checked separately. |
| Browser workflows and both themes | Pass within scope | Eleven primary-beta workflows and 142 renders passed. Another 32 clone renders passed: 12 real detail routes in both themes, the check-register alias, and three actual nonprofit pages in both themes. This closes the static sweep's detail/gating gaps. Total 174 render observations, including duplicates/mode changes and 20 narrow observations; narrow checks do not establish mobile support. No rendering faults, page exceptions or HTTP 5xx. |
| Accessibility | Pass within scope | 122 static-view and 32 supplemental axe audits found zero confirmed violations. Eight dialog/name/focus/contrast checks passed. Baseline manual review retains 122 contrast-rule occurrences and two each of QBO ARIA/table findings; extension retains 32 contrast and 20 close-glyph label occurrences. Counts describe audit occurrences, not unique defects or WCAG conformance. Human assistive technology and PDF/UA acceptance remain open. |
| Fresh Docker installation | Pass | Clean PostgreSQL volume migrated and seeded; app became healthy, non-root, read-only, capabilities dropped. |
| Accounting and payroll through HTTP | Pass | 67 checks: customer/vendor ownership guards, fractional-cent rejection, a ten-billion-dollar invoice, credits, bills, deposits, payroll processing, contractor process/void, masked/encrypted ACH settings, balanced reports. A $2,000 biweekly single-filer check withheld federal $156.15, Social Security $124, Medicare $29. |
| API inventory | Pass within scope | 616 operations on 487 paths; 295 GET probes produced no 5xx faults. Expected absent-record and validation responses are retained. Nineteen provider/token/file-specific variants were excluded from this sweep; later portal acceptance covers several. This is not acceptance of every operation. |
| Reports and documents | Pass | Seven initial PDFs parsed; CSVs downloaded; real image Poppler/Tesseract recognized the invoice. Corrected payroll-image checks passed 35 historical-snapshot and 22 independent W-2/941/940/Oregon HTTP checks, with four one-page PDFs. Changed forms were visually inspected; production Python is unchanged in the current image. Full PDF/UA conformance remains open. |
| Backup and recovery | Pass | Final-image PostgreSQL backup restored separately; complete-row hashes matched across 101 tables and 459 rows. Only the new backup registry row and its audit INSERT, written after the dump, were excluded. Balances, documents, payroll and encrypted fields matched; no unbalanced journals. |
| Restart persistence | Pass | Login, paid invoice, backup registry, encrypted ACH reveal/masking, and balanced trial balance survived app restart. |
| PostgreSQL concurrency and migrations | Pass | Final run passed concurrency 14/14, bank row-lock 5/5, schema parity 8/8, schema repair 31/31 and company upgrades 10/10. Empty-install deployment and repeated Kubernetes migration also passed. |
| On-demand control account protection | Pass | Accounts 4800 and 5900 are absent from the standard seed and conditionally skipped in that suite. A separate API-fixture run created both and passed the unchanged deletion-protection assertions: two passed, zero skipped. |
| Payroll official expected-dollar checks | Pass with release limits | Published 2026 IRS schedules, selected state rates/caps, immutable benefit bases, paid-date YTD, Oregon Paid Leave and W-2/941/940 wage bases checked independently. Historical records and processing/classification limits require the gates below. |
| Strict Compose production settings | Pass in QA | Verified private QA CA, HTTPS redirect/HSTS, Secure/HttpOnly/SameSite=Strict cookies, PostgreSQL TLS 1.3, protected endpoint, and shared Redis rate limits across two observed workers. Missing required secrets refuse configuration. |
| Kubernetes deployment | Pass | Final image config verified after forced rollout; migration Job, app/PostgreSQL/Redis readiness, paid invoice, TLS, idempotent migration, and all six allowed/blocked network-policy probes passed. Real public ingress/certificate deployment remains open. |
| Employee portal and signatures | Pass | 26 HTTP checks: token claim/revocation, protected portal pages, time submission/approval, consent, duplicate-sign refusal, document hash verification and void refusal. Synthetic documents only. |
| Nonprofit workflows | Pass within scope | 35 successful clone fixture/nonprofit HTTP checks; four semantic assertions: $100 in-kind gift/release, $60 allocation split 30/20/10 with no remainder, SOA revenue/expense/net-change deltas 100/160/-60, and balanced financial position/trial balance. Actual pages audited in both themes; posting was through the API, not every nonprofit UI form. |
| Bounded capacity | Pass within scope | 192 page reads across 50,000 invoices and 150,000 lines; 64 each at 1, 8 and 32 readers. Respective p95 latencies: 646 ms, 4.10 s and 10.36 s on the shared test host. Bulk fixtures bypass posting. Sustained deployment-specific capacity remains open. |
| Formatting, syntax, workflow and docs | Pass | Black/Ruff and workflow lint passed; 1,082 syntax checks were clean, 225 local Markdown destinations resolved, and 31 documentation/release regressions passed. API descriptions and Git integrity checked. |
| Dependencies and container CVEs | Pass with image gate | Runtime/development/Linux desktop/installed audits found no known vulnerabilities. Final app image has zero vulnerability/secret findings and a 168-component SBOM. QA-only patched Redis/NGINX images have zero findings; repository stock defaults still have patchable findings. PostgreSQL gosu version warnings remain with a recorded reachability review. |
| Secret scanning | Reviewed | Source/history hits were synthetic test fixtures; no real credential identified in scanned source/history. Ignored private environment/key files were excluded. |
| Static security and typing | Reviewed and open debt | Bandit: zero high, seven medium, 46 low. Python CodeQL: 11 default and 481 expanded; JavaScript: zero default and nine expanded. Pyright: 1,969 errors across 352 app files. Source configuration scan: 18 low, one medium. Recorded dispositions do not make these zero-alert checks. |
| Hosted checks | Earlier commit passed | [GitHub CI run](https://github.com/PNWImport/SlowBooks-Pro-2026/actions/runs/37391504600) succeeded for starting commit `1a5d90f`. It does not certify this uncommitted corrected tree. PR merge checks and code-owner review remain open. |
| Native desktop and external providers | Open | Linux launcher/contract tests cover local behavior. Signed Windows/macOS installation/update and designated live provider sandboxes remain required. |

The 12 raw skips comprise four session-guard checks for deliberately public
webhook/checkout/OAuth routes, five SQLite row-lock variants whose real
PostgreSQL counterparts passed, two absent on-demand accounts (both tested
successfully in the separate fixture run), and one empty parameter set.
No Chromium, PostgreSQL or OCR service was unavailable. Exact test identities
are in `backend/unified-summary.json`. Seven ResourceWarnings reported
unclosed SQLite connections collected during tests; they remain in the log.
Passing the entire collected suite does not mean 100% coverage or close the
release gates below.

## Corrections made during this validation

- Replaced outdated federal schedules with the exact 2026 IRS percentage-method
  rows, retaining the printed base tax at rounded checkbox boundaries.
- Corrected Washington Paid Leave rate/cap and excluded tips from Paid Leave
  and WA Cares. Gross-based premiums still apply when federal taxable pay is
  zero. Current and prior tips flow through payroll, retro, gross-up, and final
  pay calculations; termination YTD excludes later processed pay dates.
- Corrected California SDI, New York PFL/UI, and Colorado/Massachusetts/Delaware
  paid-leave caps; aligned WA/NY/OR unemployment catalog bases with engines.
  [Tax verification and remaining limits](state-tax-tables.md) provides the
  primary sources and expected-dollar cases.
- Reconstructed FICA/FUTA YTD from immutable paycheck benefit snapshots, keeping
  401(k) and income-only deductions in FICA wages. Only processed checks count,
  including already-paid checks on the same pay date; future dates, drafts and
  voids are excluded. This required no new migration.
- Added standard Oregon Paid Leave contributions using qualified current and
  historical wages, tips, retirement deferrals and the annual cap.
- Aligned W-2/W-3, EFW2, 941 and 940 with those wage bases; separated Social
  Security tips into W-2 box 7 and 941 line 5b. Four changed PDFs rendered and
  passed visual inspection. Historical taxes actually posted remain unchanged.
- Restored the initial HR Team tab; added contractor field labels, benefit and
  remittance filter names, AI action names, and distinct tax-form date groups.
  The audit interface now follows the server's administrator restriction.
  Corrected the CSV, QBO and payroll-report controls that failed target spacing.
- Corrected shared QBO/IIF result notices in dark mode. Explicit fixtures
  reproduced error contrast 3.07:1 and warning contrast 2.75:1 against the 4.5:1
  requirement; theme colors replace the hard-coded light background. The
  existing full-page regression now covers both notices in both directions.
  Final-image checks exercised eight IIF/QBO notice boxes in both themes;
  all 16 passed, with measured contrast ratios from 5.05 to 7.62.
- Rejected final newlines in company database/backup names using strict string
  anchors, with regressions that failed before the correction.
- Required `oauthlib>=4.0.0,<5` for the
  [published PKCE advisory](https://github.com/advisories/GHSA-xpv3-w29h-x7cv);
  94 QBO regressions passed after upgrading the environment.
- Fixed the Kubernetes Kustomize override that selected 2.18 instead of 2.19,
  macOS workflow shell lint, and stale API descriptions/counts.
- Fixed Compose volume initialization when private QBO cache directories exist;
  the isolated initializer can traverse them while the app keeps all
  capabilities dropped.

## Remaining release gates

1. **Payroll processing and unsupported records.** Two $1,000 payroll drafts
   staged against $184,000 of paid Social Security wages each calculate $31;
   processing both retains $62 instead of the correct combined $31. Stale-draft
   refusal/recalculation and concurrent-processing policy remain required.
   Configured taxable employer fringe is not included in wage bases: $100 on
   $2,000 cash pay produces Social Security $124 instead of $130.20 and Medicare
   $29 instead of $30.45. Legacy/imported checks without benefit snapshots
   cannot reveal qualified exclusions. Historical incorrect withholding needs
   reconciliation/amendment review; existing 941 line-7 adjustments do not prove
   non-rounding differences are legitimate. W-2 local box-18 approximation and
   comprehensive employer-payment classifications also remain limits. Complete
   EFW2/Pub 1220 validation and official e-file acceptance remain open; checked
   EFW2 RW/RT wage fields do not establish acceptance of the complete file.
2. **State payroll classification.** WA/CO/MA/DE employer-size tiers and
   exemptions, Oregon size/equivalent-plan/localization rules, simplified state
   income schedules and locality data require deployment-specific verification
   or implementation. Standard Oregon Paid Leave is now implemented. See
   [state tax tables](state-tax-tables.md) and [state withholding](state-withholding.md).
3. **Real platform and provider acceptance.** Signed Windows/macOS install and
   upgrade; designated SMTP, payment, bank feed, QBO OAuth, and AI sandboxes;
   actual public TLS/ingress; human screen-reader and complete keyboard work;
   PDF/UA assessment; sustained capacity and independent security review.
4. **Review and contribution requirements.** Recheck hosted CI on the final
   committed source and PR merge reference; obtain code-owner review and
   contributor terms/signoffs. The 76 unique nonmerge commits ahead of upstream
   currently have no `Signed-off-by`. No signoff or terms acceptance was added
   on anyone's behalf. See [CONTRIBUTING](../CONTRIBUTING.md).
5. **Static quality debt.** Reviewed nonzero scanner findings and ORM typing
   debt remain explicit. They require owner disposition or separate cleanup;
   successful functional tests do not make the type checker pass.
6. **Supporting release images.** Stock Redis reports 20 findings (4 high,
   14 medium, 2 low); stock NGINX reports 4 (2 high, 1 medium, 1 unknown).
   Clean QA-derived images prove targeted package upgrades work, but repository
   release defaults need an explicit image update. PostgreSQL reports 46 gosu
   version-based findings (1 critical, 21 high, 21 medium, 2 low, 1 unknown).
   Official Go vulnerability symbol analysis found zero affected symbols in
   that exact binary; the version warnings remain recorded. See the
   [gosu security policy](https://github.com/tianon/gosu/blob/master/SECURITY.md)
   and [Go vulnerability analysis](https://go.dev/doc/security/vuln/).

## Evidence and reproduction

Full local evidence is retained outside Git at
`/home/aitest/slowbooks-validation-20261005-NoP66g/`. Private QA environment and
certificate key files in that directory are not publication artifacts.
The local beta password is in `runtime/beta-login.txt` (mode 0600). The
artifact index is `validation-index.json`.

| Check | Files beneath the evidence directory |
| --- | --- |
| Full suite and reproducible toolchain | `backend/run-unified-final.sh`, `backend/unified-summary.json`, `backend/unified-final.log`, `backend/unified-final-junit.xml`, `backend/unified-final-coverage.json`, `backend/unified-source-sha256-start.json`, `backend/unified-source-sha256-end.json`, `backend/check_on_demand_controls.py`, `backend/on-demand-controls-junit.xml` |
| Payroll independent reproduction | `backend/tax-sources/`, `backend/staged-payroll-cap-known-defect.json`, `backend/taxable-fringe-known-defect.json`, `frontend/oregon-paid-leave-validation.json`, `security/tax-form-wage-basis-fix.json`, `security/tax-form-pdfs/` |
| Browser and visual evidence | `frontend/frontend-validation.json`, `frontend/live-final/live-crawl.json`, `frontend/live-workflows-final/workflows.json`, `frontend/accessibility-manual-review.json`, `frontend/rebuilt-image-smoke/verification.json`, `frontend/scope-extension/results.json`, `frontend/scope-extension/nonprofit-api-evidence.json`, `frontend/live-notice-final/verification.json`, browser JUnit and screenshots |
| API, accounting, PDFs and recovery | `runtime/live_acceptance.py`, `runtime/live-acceptance.json`, `runtime/api-sweep-summary.json`, `runtime/full-restore-verification.json`, `runtime/restart-verification.json`, `runtime/invoice-ocr.log`, `runtime/fica-live-acceptance.json`, `runtime/tax-form-live-acceptance.json`, `runtime/portal-acceptance.json` |
| Image/source equivalence | `runtime/image-source-parity.json`, `docker-build-final.log`, `final-image-id.json`, `security/QBO-contrast-image-chain-final.json`, `security/QBO-contrast-scan-reuse-proof.json` |
| Production transport and workers | `production/https-verification.json`, `production/runtime-security.json`, `production/missing-secrets.log` |
| Kubernetes | `k8s/checklist-final.json`, `k8s/image-final-proof.json`, `k8s/network-policy-matrix-final.json`, migration and TLS logs |
| Security and static findings | `security/checklist.json`, `security/scanner-dispositions.json`, final SARIF/JSON reports and tool checksum provenance |
| Bounded HTTP workload | `runtime/capacity_acceptance.py`, `runtime/capacity-acceptance.json`, `runtime/capacity-acceptance.log` |

The initial broad run's stale read-only test failure and the browser fixture
readiness failure remain in the evidence. The first complete unified run
passed 6,413 cases and skipped 12, with one real QBO contrast failure. Its logs,
coverage and stable source manifest are preserved under
`backend/unified-before-qbo-contrast/`. The final complete rerun after the
deterministic notice correction passed 6,414 cases with zero failures;
earlier focused passes are supporting evidence. The isolated test PostgreSQL
and auxiliary browser/capacity app containers were removed after verification.
The fresh beta, strict production QA deployment and Kubernetes QA stack remain
available; unrelated containers were preserved.
