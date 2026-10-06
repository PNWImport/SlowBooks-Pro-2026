# SlowBooks PR preparation October 5 2026

This is a local review draft against upstream 2.19.0. No PR has been opened.
The [continued beta checklist](beta-continuation-2026-10-05.md) records current
source/image results and remaining release gates. Contributor terms, author
signoffs and final hosted review remain pending.

## Suggested title

Expand payroll and HR and harden accounting and deployment after 2.19.0

## Summary

Add the payroll and HR workflows developed on this branch, connect them to the
SPA, and preserve their accounting, authorization and migration contracts
following upstream 2.19.0. Harden concurrent posting, encrypted payroll and
benefits data, audit records, backups and Linux deployment. Correct 2026 tax
constants, benefit wage bases, Oregon Paid Leave and tax-form reporting.

The continued review prevents excess payroll from stale annual-cap drafts,
unpaid retro sources and repeated retro adjustments. Add explicit ordinary
noncash employer-contribution treatment and immutable reporting while keeping
cash wages and benefit expense separate. Hold ambiguous historical earnings,
partial periods and unsupported classifications for reconciliation rather than
inferring taxes or adjusting already-paid wages.

## Changes

- Payroll: contractor runs, schedules and locations, retro/final pay, salary
  proration, tips, garnishment remittance, workers' compensation, deposit
  calendars, reports, SUI/e-file outputs, local/state withholding and encrypted
  ACH originator details with download.
- Payroll integrity: serialize writes per employee, record draft paid-history
  baselines, refuse changed history and add cancellation with exact verified
  benefit/loan refunds and time-entry release. Reserve retro source claims;
  guard work-period eligibility, units and unsupported negative adjustments.
- Benefits: nullable explicit tax classification without reclassifying existing
  codes. Add supported ordinary noncash value to withholding and immutable
  W-2/941/940/SUI wage reports. Identify it on paystubs; exclude retro/PTO
  earnings metadata from employee deductions.
- HR: benefits/enrollment, ACA/COBRA outputs, organization chart, team PTO,
  reviews and signature/audit integration; accessible SPA dialogs and controls.
- Accounting: concurrent journal/import/reconciliation guards, repeated
  process/reversal refusal, cross-party allocation protection, widened money
  precision and upstream import behavior.
- Security: encrypt protected payroll/benefits/taxpayer fields, restrict
  sensitive actions, protect private files and secrets, and sign chained audit
  checkpoints. Reject newline-suffixed identifiers and require patched OAuth.
- Operations: hardened Compose/Kubernetes, preserved encryption keys,
  PostgreSQL TLS, Redis rate limits, migration jobs/probes/network policies,
  corrected image selection, pinned workflow actions and updated documentation.

## Current validation

- [x] Complete frozen-source regression: 6,547 passed, 12 conditional skips,
  zero failures/errors, 96.92% statement coverage, all 47 browser cases;
  native OCR and PostgreSQL enabled. Finished in 29m 51.63s; the 1,157-file
  application/test/config manifest remained unchanged and matches the build.
- [x] 151 focused payroll cases, including 18 PostgreSQL/SQLite concurrency
  variants; independent before-fix and lock-removal controls retained.
- [x] Actual final-image PostgreSQL: 37 fringe/cap/cancellation checks and 25
  retro checks. Correct tax wages, once-only arrears, immutable reports and
  balanced journals; both changed one-page paystubs visually inspected.
- [x] Fresh GET sweep: 295 requests, no server errors, 617 operations on 488
  documented paths. Provider/token/file exclusions retain their actual scope.
- [x] Downloaded backup restored independently: complete-row hashes match all
  101 tables and 1,518 rows; only the post-dump backup row and its INSERT audit
  excluded. Restart preserves old and new payments and encrypted ACH settings.
- [x] Final-image native Poppler/Tesseract recognized the paid invoice total.
- [x] Strict HTTPS, private QA CA verification, redirect/HSTS, secure cookies,
  shared Redis login throttling, two observed workers and PostgreSQL TLS 1.3.
- [x] Final Kubernetes image configuration and source hashes, migration no-op,
  financial preservation, readiness/TLS and six network-policy checks.
- [x] Final app image: zero known vulnerabilities/secrets, 168-component SBOM,
  all 70 installed Python distributions independently audited clean. Static
  source findings and stock supporting-image updates remain explicit gates.
- [ ] Signed Windows/macOS installation, designated live provider sandboxes,
  payroll jurisdiction approval, human accessibility/PDF-UA acceptance,
  sustained capacity, independent security and code-owner review.

The [first completed beta audit](beta-readiness-2026-10-05.md) retains the
broader accounting, nonprofit, portal, UI/accessibility and capacity results
with their original build provenance: 6,414 passed/12 conditional skips,
85 Node tests, 11 live workflows and 154 axe audit occurrences. Those counts
are historical observations, not additional final-image executions.

The [hosted CI run](https://github.com/PNWImport/SlowBooks-Pro-2026/actions/runs/37391504600)
was rechecked online and succeeded for starting commit `1a5d90f`. It does not
certify these local changes. Hosted CI, PR security/merge-reference checks and
code-owner review must run on the eventual committed tree after authorization.

## Database changes

The migration chain now ends at `b7fringe2026105`, after `m3heads2026105`.
Its nullable `benefit_codes.employer_tax_treatment` column does not backfill
existing taxable flags. Upgrade/downgrade fixtures preserve old flags and
snapshot bytes; actual PostgreSQL/Kubernetes upgrades and repeat migrations
passed. New draft/earnings/reservation/retro claims use immutable JSON
snapshots. Preserve deployment encryption and session keys.

Legacy missing snapshots, incorrect historical taxes and unverifiable retro
pricing need reconciliation. Special fringe exclusions/valuation, taxable
post-tax matches and employer-paid employee-tax gross-ups remain unsupported.
Existing accounting/audit drift is not automatically repaired. The checklist
records additional state/local, e-file, provider and supporting-image gates.

## Security implications

The branch changes authentication, authorization, encryption, private uploads,
audit integrity, provider credentials and deployment trust boundaries. Tests
cover denial paths, roles, encryption/masking, recovery and transport/rate
limits. Reviewed nonzero Bandit/CodeQL/configuration findings and Pyright typing
debt remain recorded; functional results are not an independent penetration
assessment or production-release approval.

## Contributor terms

- [ ] Author has read and accepted the Contributor Terms in
  [CONTRIBUTING](../CONTRIBUTING.md), has the right to contribute and supplies
  their own Signed-off-by for relevant commits.

All 76 unique nonmerge commits ahead of upstream currently lack signoff. This
draft does not accept terms, approve licensing or rewrite anyone's commits.

## Review artifacts

Current logs, before/after regressions, PDFs, coverage, image descriptors and
scanner reports are retained in
`/home/aitest/slowbooks-validation-20261005-continuation-QivGHp/`. Original broad
beta evidence remains unchanged in
`/home/aitest/slowbooks-validation-20261005-NoP66g/`. Attach sanitized examples
when submitting; exclude environment files, certificate keys, payroll/bank
details, browser credentials and raw backups.
