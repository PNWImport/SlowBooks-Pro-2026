# HIPAA Compliance Assessment

**Status:** SlowBooks Pro 2026 is **not a HIPAA-covered system by default.**
It's accounting and payroll software, not a healthcare information system.
This document is an honest accounting of where its controls already align
with the HIPAA Security Rule and where the gaps are — so a business that
needs HIPAA-style assurances can make an informed decision.

---

## 1. Does HIPAA apply to SlowBooks?

HIPAA applies to **Covered Entities** (healthcare providers, health plans,
healthcare clearinghouses) and **Business Associates** that handle
**Protected Health Information** (PHI) on their behalf. PHI is anything
that identifies an individual *and* relates to their physical or mental
health, healthcare provision, or payment for healthcare.

**What SlowBooks stores that is potentially HIPAA-adjacent:**

| Data | HIPAA classification | Notes |
|------|----------------------|-------|
| Employee name + address | Not PHI by itself | Becomes PHI only when combined with healthcare information |
| Employee SSN (last 4) | Not PHI | An identifier, but no health data attached |
| Employee bank routing / account # | Not PHI | Financial data, encrypted at rest |
| Pay-stub gross / withholding | Not PHI | Wage data |
| HSA deduction *amount* | Not PHI | Reveals only that an HSA exists, not health details |
| Health insurance deduction *amount* | Not PHI | Same — premium amount without enrollment/claim details |
| Pre-tax FSA / dependent-care amount | Not PHI | Same |
| Insurance carrier name | Borderline — stored, **encrypted** | `BenefitPlan.carrier_name`, Fernet at rest |
| Health-plan enrollment + coverage dates | **Likely ePHI in a BA context** — plaintext | `BenefitEnrollment` — identifies a person *and* relates to payment for healthcare. Coverage dates and plan kind are filtered/joined on, so encrypting them needs a blind index (§ 4) |
| Covered dependents (name, DOB, SSN last-4) | **Likely ePHI in a BA context** — **encrypted** | `BenefitDependent`, Fernet at rest; DOB is an identifier under the safe-harbor list |
| Months-of-coverage (ACA 1095) | **Likely ePHI in a BA context** | Derived, not stored, but rendered per person by `/api/tax-forms/1095` |
| COBRA qualifying event + plan | **Likely ePHI in a BA context** | Coverage-loss event tied to a named individual |
| Actual claims, diagnoses, treatment | Would be PHI | **We still don't store any of this** |

**Default verdict:** A business running SlowBooks for normal accounting +
payroll is not a HIPAA-regulated workflow. Customer becomes a Business
Associate only if they explicitly use the app to handle PHI on behalf of
a Covered Entity, which isn't the design intent.

> ⚠ **This verdict narrowed when the benefits module landed.** Before it,
> the app stored only deduction *amounts* — the premium came out of a
> paycheck and nothing said what it bought. It now stores health-plan
> enrollment, carrier names, coverage windows, and covered dependents, and
> derives per-person months-of-coverage for ACA reporting. That is
> individually identifiable information relating to payment for
> healthcare. The identifying fields (carrier name, dependent name/SSN
> last-4/DOB) are now Fernet-encrypted at rest — see § 164.312(a)(2)(iv) —
> which closes the worst of it; the enrollment metadata around them is not.
> It is still not a Covered Entity workflow (an employer
> administering its own group plan is generally acting as employer, not as
> a health plan), but the earlier line "we don't store any of this" is no
> longer true, and § 4's gap list applies with more force. If a deployment
> has any Business Associate exposure, treat the four benefit tables as
> ePHI and read § 4 as required work, not optional hardening.

---

## 2. HIPAA Security Rule mapping

For businesses that want HIPAA-aligned controls regardless of strict
applicability, here's where each Security Rule technical safeguard maps
to existing SlowBooks behavior.

### § 164.312(a)(1) — Access Control

| Spec | Implementation |
|------|---------------|
| Unique user identification (R) | Single-operator design; no multi-tenant users yet |
| Emergency access procedure (R) | Manual — operator has the master password + backup files |
| Automatic logoff (A) | ✅ `SESSION_IDLE_TIMEOUT_SECONDS` (default 14400s / 4h) clears sessions |
| Encryption + decryption (A) | ✅ Fernet for bank PII at rest; AES-128-CBC + HMAC-SHA256 |

### § 164.312(b) — Audit Controls

> "Implement hardware, software, and/or procedural mechanisms that record
> and examine activity in information systems that contain or use ePHI."

| Mechanism | Implementation |
|-----------|---------------|
| Login attempts | ✅ `LoginAttempt` table — success / failure with IP + UA |
| Database row writes | ✅ `register_audit_hooks(SessionLocal)` in `app/main.py` writes an `audit_log` row for every create / update / delete via SQLAlchemy event hooks |
| Document tampering | ✅ `DocumentAudit` linked hash chain + SHA-256 content hash printed in generated-document footers. Detects alteration, deletion, reordering and insertion; `GET /api/document-audits/chain/verify` reports the first break |
| Portal token usage | ✅ `Employee.portal_token_last_used` rolls forward on every authenticated portal request |

### § 164.312(c)(1) — Integrity

> "Implement policies and procedures to protect ePHI from improper
> alteration or destruction."

| Spec | Implementation |
|------|---------------|
| Authentication of ePHI (A) | ✅ Fernet ciphertext carries HMAC; tampered ciphertext fails to decrypt and returns None |
| Document integrity | ✅ Linked hash chain over `document_audits` (below) + per-document SHA-256 in generated PDFs; auditor re-verifies by regenerating |
| Truncation detection | ✅ `audit_checkpoints` pins (tip id, tip hash, row count); `GET /api/document-audits/chain/checkpoints/{id}/verify` |

**`document_audits` is a linked hash chain.** Each row commits to its
predecessor:

```
chain_hash(N) = SHA256(prev_hash | content_hash | doc_type | doc_key | created_at)
prev_hash(N)  = chain_hash(N-1)          # genesis: 64 zeros
```

Because `doc_type`, `doc_key` and `created_at` are inside the hash, a row
cannot be relabelled or back-dated while keeping its linkage intact either.

| Attack | Detected? | By what |
|--------|-----------|---------|
| Alter a document's content | ✅ | `content_hash` no longer reproduces on re-render |
| Alter an audit row's fields | ✅ | `chain_hash` no longer recomputes from the row |
| Delete a row from the middle | ✅ | successor's `prev_hash` no longer matches |
| Reorder or splice in rows | ✅ | same linkage break |
| Back-date a row | ✅ | `created_at` is inside the chain hash |
| **Truncate the tail** | ✅ *with a checkpoint* | a shortened chain is internally valid, so linkage alone cannot catch this — `audit_checkpoints` can |
| Delete rows **and** checkpoints, with full DB write access | ❌ | keep checkpoint copies off the box; see operations.md |

Appends take a row lock on the current tip (`SELECT … FOR UPDATE` on
PostgreSQL; SQLite serializes writers), so two concurrent writers cannot
fork the chain.

**Baseline honesty.** Rows written before the chain existed were backfilled
deterministically in id order by migration `a2b3c4d5e6f9`. That establishes
a verifiable baseline going forward. It is **not** retroactive proof that
pre-backfill history was untampered — a backfill computes a valid chain over
whatever rows are present, including a set someone had already edited.
Checkpoint immediately after migrating, and keep that checkpoint off-box.

`tests/test_document_audit_integrity.py` exercises every row of the table
above, including the truncation case.

### § 164.312(d) — Person or Entity Authentication

| Spec | Implementation |
|------|---------------|
| Verify identity before access | ✅ Argon2id password (default cost ~100ms/verify); 5/min rate-limited login |
| Session integrity | ✅ Starlette signed cookie + session rotation on login |
| Portal authentication | ✅ 192-bit `secrets.token_urlsafe(24)` token; 90-day idle + 1-year hard expiry |

### § 164.312(e)(1) — Transmission Security

| Spec | Implementation |
|------|---------------|
| Integrity controls (A) | ✅ HTTPS enforced; HSTS `max-age=63072000; includeSubDomains; preload` |
| Encryption (A) | ✅ `FORCE_HTTPS=true` (default in production) + `HTTPSRedirectMiddleware`; session cookie carries `Secure` flag |
| Database transport | ✅ Startup fails hard in production if `DATABASE_URL` lacks `sslmode=require` |

### § 164.312(a)(2)(iv) — Encryption at Rest

| Field | Status |
|-------|--------|
| Bank routing # | ✅ Fernet-encrypted |
| Bank account # | ✅ Fernet-encrypted; only last-4 plaintext |
| AI provider API keys | ✅ Fernet-encrypted via `app/services/crypto.py` |
| Password hashes | ✅ Argon2id (one-way) |
| Employee SSN | ⚠ Only last 4 digits stored — full SSN never collected |
| Employee name / address | ⚠ Plaintext (not PHI in HIPAA terms) |
| HSA / health-insurance deduction amounts | ⚠ Plaintext (not PHI in HIPAA terms) |
| Benefit carrier name | ✅ Fernet-encrypted |
| Benefit dependent name / SSN last-4 / DOB | ✅ Fernet-encrypted |
| Benefit plan kind, coverage dates, premiums | ⚠ Plaintext — queried and joined on; needs a blind index to encrypt |

---

## 3. Administrative + Physical Safeguards

These are deployment-time controls, not code controls. SlowBooks can be
configured to support them but doesn't enforce them on its own.

| Safeguard | Notes |
|-----------|-------|
| § 164.308 Security Management Process | Customer responsibility — risk analysis, sanctions policy, etc. |
| § 164.308 Workforce Security | Customer responsibility — background checks, termination procedures |
| § 164.308 Information Access Management | SlowBooks is single-operator; multi-user RBAC is not implemented |
| § 164.308 Security Awareness and Training | Customer responsibility |
| § 164.308 Security Incident Procedures | Customer responsibility; SlowBooks logs help with detection |
| § 164.308 Contingency Plan | ✅ `pg_dump` backup via `app/services/backup_service.py` + restore flow |
| § 164.308 Evaluation | Periodic re-assessment — customer responsibility |
| § 164.308 Business Associate Contracts | Customer responsibility — if SlowBooks operator becomes a BA |
| § 164.310 Facility Access Controls | Physical deploy environment (datacenter / office) — customer responsibility |
| § 164.310 Workstation Use / Security | Customer responsibility |
| § 164.310 Device and Media Controls | Customer responsibility |

---

## 4. Gaps if you wanted to run SlowBooks in a HIPAA context

If a customer chose to store ePHI in SlowBooks (e.g. health-insurance
enrollment details beyond the deduction amount), here's what would need
to change to fully align with the Security Rule:

| Gap | Severity | Fix |
|-----|----------|-----|
| **Enrollment metadata still plaintext** | Medium | Dependent identifiers and carrier names are now Fernet-encrypted, but plan kind, coverage windows and the employee foreign key are not — they are filtered, sorted and joined on, and Fernet output is randomized. An attacker with table access can still tell *which employees hold medical coverage over which months*, just not who the dependents are. Closing it needs deterministic blind-index columns alongside the encrypted values |
| **Audit checkpoints are not cryptographically signed or off-boxed** | Medium | The hash chain (§ 164.312(c)(1)) now detects alteration, deletion and reordering, and checkpoints detect truncation — but an attacker with full database write access can delete the checkpoints too. Fix: sign checkpoints with an operator-held key and ship them off the box (WORM storage, or a second system) |
| **No role-based access control** | High | SlowBooks is single-operator. HIPAA expects "minimum necessary" — different staff see different data. Would require a user model + role assignment + per-field access checks |
| **Employee data not encrypted at rest** | Medium | Names, addresses, hire date, etc. are plaintext. If treated as PHI, would need Fernet wrapping (same scheme as bank fields) |
| **No data-retention enforcement** | Medium | Pay stubs and employee records stay forever. HIPAA expects retention/destruction policies — would need a configurable retention period + automated purge |
| **No breach-notification flow** | Medium | If the audit log detects tampering or unauthorized access, there's no automated alerting. Would need email/webhook integration |
| **No employee data-export endpoint** | Low | Right-to-access — the portal lets an employee see their own data, but there's no "give me everything you have on me as a JSON export" feature |
| **No Business Associate Agreement (BAA) template** | Low | Documentation gap. Vendor would need to provide a signable BAA |
| **No FIPS 140-2 attestation** | Low | Python's `cryptography` library uses OpenSSL underneath; FIPS mode depends on the OpenSSL build the customer's OS ships. SlowBooks doesn't enforce a FIPS-validated build |
| **Encryption-at-rest key escrow** | Low | `PAYROLL_ENCRYPTION_SECRET` is operator-managed. HIPAA HSM / KMS integration would be a customer-driven enhancement |

---

## 5. What we already do that exceeds typical small-business norms

These aren't strictly HIPAA-required but are good signals for any
compliance regime (HIPAA, SOC 2, PCI-DSS):

- **Versioned ciphertext** (`v1:` prefix) — supports zero-downtime key rotation
- **Login + document audit trails**, the latter a linked SHA-256 hash chain
  with pinned checkpoints (see § 164.312(c)(1))
- **Idle session timeout** + automatic logoff
- **Startup fail-hard checks** on production misconfig (encryption secret, DB TLS, FORCE_HTTPS)
- **Rate-limited login** + Argon2id password hashing (~100ms cost)
- **Content-Security-Policy** + HSTS + strict CORS
- **Atomic secret file writes** (`mkstemp` + `os.replace`)
- **CSV formula-injection protection** in exports
- **No hardcoded secrets** anywhere in the codebase
- **SSRF protection** on AI provider URL configuration

---

## 6. Recommendations for HIPAA-conscious deployments

If a customer is running SlowBooks for a small healthcare-adjacent business
(e.g. a physical therapy practice's accounting, where they want HIPAA-style
care even though only payroll/financial data is in scope):

1. **Set strong production env vars** — see [security-hardening.md](security-hardening.md) deployment checklist
2. **Run behind a TLS-terminating reverse proxy** with a valid cert (Let's Encrypt is fine)
3. **Restrict database access** — `pg_hba.conf` to only the app host, `sslmode=verify-full` with cert pinning
4. **Configure encrypted backups** — `pg_dump` output should be GPG-encrypted at rest if it leaves the server
5. **Set up offsite backup encryption keys** separately from the database — never co-locate the encryption secret with the data
6. **Enable system audit logging** at the OS level (auditd / journald) — captures process-level events SlowBooks doesn't see
7. **Rotate `PAYROLL_ENCRYPTION_SECRET` annually** — use the `PAYROLL_ENCRYPTION_SECRET_PREV` flow for zero-downtime rotation
8. **Review `login_attempts` and `audit_log` tables weekly** — even a quick "show me failed logins in the last 7 days" run catches slow probes

---

## 7. Honesty notes

- This document was written by an engineer doing a code audit, not by a HIPAA compliance officer. If HIPAA is contractually required for your deployment, retain a qualified compliance professional to do a real risk assessment.
- "Aligned with" HIPAA's technical safeguards is not the same as "HIPAA-certified." The OCR doesn't certify software products; certification, if any, applies to the deployed system as operated by the Covered Entity or Business Associate.
- The pyjwt PYSEC-2025-183 advisory (no upstream fix) is currently tracked in `docs/todo.md` — note it in any formal risk assessment until a patched release lands.

---

**Last updated:** 2026-08-18 — revised after the payroll/HR expansion.
Two substantive changes: the benefits module moved the PHI posture (§ 1),
and the `document_audits` ledger-vs-chain distinction is now stated
accurately (§ 164.312(c)(1)) instead of being papered over by the word
"chain" — and then made into an actual linked chain with checkpoints, so
the claim and the code now agree. Follow-up in the same series: the
benefits ePHI identifiers are now encrypted at rest (§ 164.312(a)(2)(iv)),
leaving enrollment metadata as the remaining plaintext surface.
