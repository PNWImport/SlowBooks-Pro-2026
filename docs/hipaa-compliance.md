# HIPAA readiness assessment

Reviewed 2026-09-07 against the local payroll/HR branch. This is an engineering
assessment, not a legal opinion, certification, or approval to process ePHI.
Application safeguards are implemented; deployment readiness remains unverified.

## Applicability

HIPAA obligations depend on the organization, its role, and the information it
handles—not the software's label. Employment records held in an employer capacity
are generally outside the Privacy Rule; group-health-plan administration needs a
separate assessment. Do not classify enrollment, premiums, or dependent records
as automatically outside HIPAA. See HHS guidance on
[employment records](https://www.hhs.gov/hipaa/for-individuals/employers-health-information-workplace/index.html)
and [plan sponsors](https://www.hhs.gov/hipaa/for-professionals/faq/499/am-i-a-covered-entity-under-hipaa/index.html).

Inventory benefits coverage, dependents, ACA outputs, attachments, free-text
notes, exports, logs, and backups before deciding whether a workflow handles
ePHI. Review hosting, support, email, AI, and other integrations separately;
do not send ePHI to them without an approved data flow and applicable agreements.
HHS explains [cloud-provider and business-associate responsibilities](https://www.hhs.gov/hipaa/for-professionals/special-topics/health-information-technology/cloud-computing/index.html).

## Implemented controls and limits

| Area | Code evidence | Limit |
|---|---|---|
| Identity and access, § 164.312(a), (d) | Admin-only payroll/HR policy extended to branch routes; employee directory redacted. Session principals rechecked against current accounts; stale credentials and pre-upgrade cookies rejected. | Broad roles, not per-field or health-plan-specific duties. Review offboarding, API tokens, and deployment access separately. |
| Session expiry | Configurable idle expiry; default four hours | Zero disables idle expiry. API-token access follows a different path; validate token revocation separately. |
| Audit controls, § 164.312(b) | Login records, actor-attributed ORM change records, portal access records, document ledger | ORM hooks do not establish comprehensive read/export logging or cover direct SQL writes. Monitoring remains operational work. |
| Integrity, § 164.312(c) | Document hash chain, signed checkpoints, export/verification (`app/services/document_audit.py`, `app/services/audit_signing.py`) | Signing secret and off-box retention must be configured. Not every audit table is hash-chained. Host/key compromise remains a threat. |
| Transmission, § 164.312(e) | Production HTTPS checks; PostgreSQL TLS-mode validation | Accepted `require` mode does not establish hostname verification. Use `verify-full` with trusted CA configuration; validate proxy, browser, and database connections. |
| Recovery | SQLite/PostgreSQL backup and restore paths (`app/services/backup_service.py`) | Backup creation is not backup encryption, offsite retention, or a tested contingency plan. |

These are selected technical mappings, not a complete assessment of all HIPAA
rules. Administrative and physical safeguards, documented risk analysis, and
periodic evaluation also apply. Addressable safeguards are not simply optional.
See the [HHS Security Rule overview](https://www.hhs.gov/hipaa/for-professionals/security/laws-regulations/index.html)
and [risk-analysis guidance](https://www.hhs.gov/hipaa/for-professionals/security/guidance/guidance-risk-analysis/index.html).

## Encryption at rest — § 164.312(a)(2)(iv)

The models implement field encryption, not whole-database encryption:

- `Employee`: street-address lines and SSN last-four are encrypted. Names,
  city/state/ZIP, email, hire dates, and notes remain ordinary columns.
- Bank routing/account fields are stored as encrypted values.
- `BenefitPlan`: carrier and kind are encrypted. The kind blind index exposes
  equality/frequency; it does not conceal category distribution.
- `BenefitEnrollment`: coverage dates are encrypted. Employee/plan linkage and
  status remain readable.
- `BenefitDependent`: name, DOB, and SSN last-four are encrypted. Linkage and
  relationship category remain readable.

See `app/models/payroll.py`, `app/models/bank_accounts.py`,
`app/models/benefit_coverage.py`, and `app/services/encryption.py`.
Readable fields and their combinations can still be sensitive. Field encryption
does not protect decrypted responses, downloaded PDFs, attachments, or all logs.
Use risk-appropriate volume/backup encryption and separately protected keys.

### Audit-copy hardening in this pass

A synthetic in-memory probe reproduced encrypted source values being copied as
plaintext into `audit_log.new_values`. The update path also bypassed the existing
password-hash redaction.

The ORM audit hook now redacts encrypted string/date/enum values, password
hashes, portal tokens, API-token hashes, and settings values on INSERT, UPDATE,
and DELETE. It retains actor, action, record identity, and changed-field names.
This prevents new copies through that hook; it is not blanket PHI redaction.
Names, notes, other unencrypted fields, and manually supplied audit events still
require data-flow review. Regression tests: `tests/test_audit_sensitive_values.py`.

**Existing audit rows and backups are unchanged.** Treat historical audit JSON
as potentially containing sensitive values. Restrict access, assess exposure,
and plan any redaction/migration with retention and incident-response owners.
Do not delete or rewrite audit history without an approved preservation plan.

## Before an ePHI deployment

- [ ] Document applicability, data inventory, risk assessment, security/privacy
  owners, and approved uses/disclosures.
- [ ] Address historical plaintext audit copies; verify new-write redaction and
  test benefits/payroll access for each role, including exports and tokens.
- [ ] Assess stronger authentication, emergency access, session expiry,
  offboarding, and separation of health-plan and bookkeeping duties.
- [ ] Validate TLS, encrypted storage/backups, key recovery/rotation, host/device
  security, and a restore drill with recovery objectives.
- [ ] Configure audit review/alerts and off-box checkpoint exports. Without a
  signing key, checkpoints are unsigned. HMAC keys permit signing as well as
  verification; a compromised host can forge new artifacts. Previously retained
  external artifacts provide a separate reference, not prevention of compromise.
- [ ] Establish incident assessment and applicable breach notifications,
  workforce training, vendor/BAA review, and periodic reassessment.
- [ ] Establish applicable access/amendment/disclosure procedures and retention,
  legal-hold, and secure-disposal policies across primary data and backups.

HIPAA's six-year Security Rule documentation period is not a blanket instruction
to purge employee or medical records after six years. The Privacy Rule itself
does not set medical-record retention periods; other laws can apply. See
[HHS retention guidance](https://www.hhs.gov/hipaa/for-professionals/faq/580/does-hipaa-require-covered-entities-to-keep-medical-records-for-any-period/index.html).
A JSON-export endpoint, automated notification feature, BAA template, or a
particular key-management product alone does not establish compliance.

## Evidence and operations

See [validation results](validation.md) for test scope and limitations, and
[operations](operations.md) for backups and audit-checkpoint procedures.
Prior passing tests do not certify this deployment. This pass did not inspect a
live customer database, validate organizational policies, or perform a penetration
test. Obtain qualified review before representing a deployment as HIPAA compliant.
HHS [does not certify products as Privacy Rule compliant](https://www.hhs.gov/hipaa/for-professionals/privacy/guidance/index.html).
