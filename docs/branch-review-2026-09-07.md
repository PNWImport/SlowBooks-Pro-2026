# Branch review — `claude/main-branch-protection-2tqh90`

> **Superseded — this branch has since merged `origin/main` (345 commits).**
> Findings below describe the branch *before* that merge and are kept as a
> point-in-time record, not as a current description of the tree. What the
> merge changed is summarised at the end of this file.

**Date:** 2026-09-07 · **Head:** `9a5b39a` · **Base:** `ece80e7`
**State:** 1365 tests pass, 2 skip, `black` + `ruff` clean at the pinned versions.

This branch is **not** merged into `main` and is 345 commits behind it.
Everything below is on the branch only.

---

## 1. Nothing of yours was deleted

Three separate worries, all checked against git history rather than
assumed:

| Worry | Finding |
|---|---|
| "Did they remove my payroll/security tests?" | No. `main` has **106** test files; this branch has **85**. `test_payroll.py`, `test_payroll_tier3.py`, `test_tier3.py`, `test_auth.py` are all still in `main`, untouched. |
| "Did they remove my audit chain?" | No — **`main` never had it.** `git log -S chain_hash` on `main` returns nothing, and `c514ce6` / `bcd8e96` are not ancestors of `main`. The chain was never merged there. |
| "Did someone take my ideas?" | No. `c9dcc47` (benefits engine) and `f48f2f7` (payroll package split) are **your own commits**, authored by TVonHolten and co-authored by Claude in session `01NKHh4ur44kz4YNjbQd85kW`. Parallel branches, same owner. |

The five security suites that are not in `main` — `test_encryption.py`,
`test_portal_security.py`, `test_security_headers.py`,
`test_document_audit_integrity.py`, `test_audit_checkpoint_signing.py` —
did not exist at the fork point either. They were written on this branch
and have never reached `main`.

---

## 2. Access control: every route is gated

Previously only the 47-entry backend-only allowlist was tested; the other
~500 routes were *assumed* gated because the middleware is deny-by-default.
Assumption is not a control, so `tests/test_no_ungated_endpoints.py` now
enumerates the whole route table off `app.routes`, calls **all 383
method/path pairs anonymously**, and requires each to refuse or appear on a
justified public list.

**Result: no ungated doors.** The public surface is exactly `/`, `/health`,
`/favicon.ico`, `/analytics`, `/static/*`, `/api/auth/*`, `/pay/*`, the
Stripe webhook, and the portal favicon (the employer logo, 204 when unset).

Three things this turned from assumption into fact:

- **`/portal/*` and `/api/qbo/callback` are not public.** They are exempt
  from the *session* middleware but carry their own credential and answer
  401 without it. The first version of the exempt list had this backwards.
- **Token-in-path portal routes answer 404, not 401,** for an unknown
  token — deliberately indistinguishable from a nonexistent route, so
  status codes cannot be used to enumerate valid tokens.
- **`POST /portal/*` answers 422, not 401.** FastAPI validates the request
  body before the auth dependency resolves, so an anonymous POST names the
  missing fields. No data is served and auth is not bypassed — a well-formed
  body still 401s — but the request schema leaks. Pinned in its own test so
  closing it later is a deliberate act rather than accidental drift.

The Stripe webhook is the only genuinely anonymous data path. It verifies
the request signature, and `tests/test_stripe_webhook_signature.py` proves a
forged `checkout.session.completed` records no `Payment` row.

---

## 3. Encryption at rest: what is and is not covered

**Encrypted (Fernet, versioned ciphertext, rotatable):**

| Table | Columns |
|---|---|
| `employee_bank_accounts` | `routing_number_enc`, `account_number_enc` |
| `vendor_bank_accounts` | `routing_number_enc`, `account_number_enc` |
| `benefit_plans` | `kind` (+ blind index), `carrier_name` |
| `benefit_enrollments` | `coverage_start`, `coverage_end` |
| `benefit_dependents` | `name`, `ssn_last_four`, `dob` |

**Honest gaps — not encrypted:**

- **`benefit_enrollments.employee_id` is a plaintext FK.** Someone with DB
  read access learns *which named employees have an enrollment*; the plan
  kind and coverage window stay protected. Encrypting a join key is not
  practical, but the claim should be "coverage details are protected", not
  "coverage is private".
- `employees.ssn_last_four`, `address1/2`, `email`, `pay_rate` — plaintext.
- `contacts` (customers/vendors): `tax_id`, `email`, `phone`, addresses,
  `account_number` — plaintext.
- `garnishment_orders.agency_address` — plaintext.

For a HIPAA posture the first item is the one to decide on: the ePHI
*values* are encrypted, but the *fact of enrollment* is not.

---

## 4. Dependency CVEs: 10 found, 9 closed

`pip-audit` reported 10 advisories across three packages. **Two of the pins
blocking the fixes were ones we wrote ourselves.**

| Package | Was | Now | Why |
|---|---|---|---|
| `cryptography` | `>=46.0.5,<47.0` | `>=50.0.0` | `GHSA-537c-gmf6-5ccf` — the wheel statically links a vulnerable OpenSSL, which applies regardless of which APIs we call. Plus three X.509/PKCS7 advisories we do not exercise. The `<47.0` cap was blocking every fix, so it was removed, not raised. |
| `python-multipart` | `==0.0.27` | `>=0.0.31` | Reachable on real endpoints — it parses every upload and form. `PYSEC-2026-3040`: a negative `Content-Length` turned a bounded read into read-until-EOF. |
| `black` | `>=24.8,<25` | `>=26.3.1,<27` | `PYSEC-2026-2120/2121`. **Our own `<25` cap was holding back a security fix.** Bump is free — 26.5.1 formats this tree byte-identically to 24.10. Dev-only, not in the production image. |

`cryptography` is what Fernet runs on, so it backs the bank columns and the
ePHI above. Fernet's format is stable across these releases; existing
ciphertext still decrypts, verified by the full suite on 50.0.1.

**Still open: `weasyprint` `PYSEC-2026-3412` — no fixed release exists.**
Not applicable to us: the advisory requires HTML presentational hints to be
enabled, and every call site uses `write_pdf()` with the default `False`.
Because that is a call-site property one edit could undo,
`tests/test_pdf_security.py` pins it and also asserts every string-rendered
PDF passes the SSRF-blocking `url_fetcher`.

---

## 5. Environment discrepancy worth knowing

`Dockerfile` and all four CI jobs target **Python 3.13**. The container
these 1365 tests ran in is **Python 3.11.15**. Nothing failed because of
it, but the suite has not actually been exercised on the version that ships.
Worth one CI run before trusting the result.

---

## 6. Merging with `main` is a port, not a merge

An integration attempt is preserved on the local branch
`wip/merge-main-2026-09-07` (never pushed). It resolved all 26 conflicts and
got the app importing with 544 routes, then failed 72 tests. Two of those
resolutions were **wrong**, and the reasoning is worth recording:

**The audit chain.** Your `DocumentAudit` has `prev_hash`, `chain_hash`, and
`AuditCheckpoint`. `main`'s has none of them — it is the older
independent-rows ledger. The merge silently let `main`'s win and took the
tamper-evidence with it; that is the 24-failure cluster in
`test_audit_checkpoint_signing`. **Yours is a strict superset and must win.**

**The benefits models.** These are *not* renames:

| | This branch | `main` |
|---|---|---|
| Models | `BenefitPlan` / `BenefitEnrollment` / `BenefitDependent` | `BenefitCode` / `BenefitRate` / `EmployeeBenefit` / `BenefitYTD` |
| Tables | `benefit_plans`, `benefit_enrollments`, `benefit_dependents` | `benefit_codes`, `benefit_rates`, `employee_benefits`, `benefit_ytd`, … |
| Answers | *who had which coverage which months, plus dependents* | *deduct 5% pre-tax, post to 2380* |

`main`'s benefits model contains **zero** dependent, coverage-window, MEC or
carrier fields — it cannot produce a 1095-C. Aliasing one onto the other
would be lossy nonsense. But there is **no table-name collision**, so they
coexist in one schema. The only real conflict is the Python filename
`app/models/benefits.py`; rename this branch's to `benefit_coverage.py` and
the ePHI encryption and blind index survive untouched.

**Remaining work for a real port:** rename the one colliding module,
re-parent three migrations onto `main`'s chain tip, move the ACA page off
`/hr/benefits` (`main` took that route), and satisfy two new gates `main`
added that this branch's older files do not meet — a nonprofit terminology
system (`workers_comp.js` says "Class" unwrapped) and stricter accessibility
checks (`compliance.js`, plus `cobra_notice.html` / `state_sui.html` missing
`lang` and `title`).

---

## 7. Two earlier claims that were wrong

- I recommended dropping this branch's benefits implementation in favour of
  `main`'s engine. That was wrong — they model different domains and do not
  collide. Keep both.
- The first merge attempt let `main`'s simpler `DocumentAudit` win. Also
  wrong, for the same reason: ours is a superset.

---

## 8. Open items

- Decide on `benefit_enrollments.employee_id` (plaintext join key).
- Close or accept the `POST /portal/*` 422-before-401 schema disclosure.
- Run the suite on Python 3.13.
- `k8s/`: NetworkPolicies, PDB/HPA, off-cluster backups, and real secret
  management (these are plain Kubernetes Secrets — base64 in etcd, not
  encrypted) before real data.
- Verify the 47 state withholding tables and 32 locality files; all ship
  `"verified": false`, and the e-file layouts have never been run through
  AccuWage.

---

## Post-merge status (appended after merging `origin/main`)

The merge landed and the tree is green: **3065 pass, 12 skip, 0 fail**.

Two corrections to the record above:

- **The five security suites are named differently.** `test_encryption.py`,
  `test_portal_security.py` and `test_security_headers.py` do not exist and
  never did. The equivalent coverage lives in `test_encryption_coverage.py`,
  `test_settings_encryption.py`, `test_benefits_encryption.py`,
  `test_portal_link.py`, and — since the merge — `test_cors.py`, which now
  also asserts that security headers are present on a 401.
  `test_document_audit_integrity.py` and `test_audit_checkpoint_signing.py`
  are real and unchanged.

- **"Every route is gated" held, but the gate was in the wrong place.**
  `require_session` was registered *outside* CORS and the security-header
  middleware, so preflights were answered 401 with no
  `Access-Control-Allow-Origin` and every 401 shipped with no CSP. Routes
  were gated; the responses the gate produced were not protected. Fixed by
  reordering the middleware stack, with regression tests in `test_cors.py`.

The merge also silently dropped a number of this branch's behaviours —
tips, mid-period proration, garnishment remittance rows, per-state SUTA
rates, the work-location tax fallback and `tax_id` encryption among them.
All are restored; see the commits between the merge and here.
