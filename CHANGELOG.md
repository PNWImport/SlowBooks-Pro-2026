# Changelog

Notable changes between releases. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/). The internal build order
used during development is captured here so the README can stay focused
on what the software does, not on what sprint shipped what.

## [Unreleased]

### Payroll / HR module
- Self-service portal now branded with the employer's company name and logo
  (was generic "Employee Portal — Slowbooks Pro 2026"). Same for the
  state new-hire report PDF.
- Frontend ↔ backend wiring audit: fixed three `API.delete` typos
  (employees, deductions), added missing `GET/PUT /api/pto/policies/{id}`,
  added `/approve` and `/reject` aliases for `/decision`.
- Onboarding (`#/hr/onboarding`) — 8-task checklist per employee with
  completion %, e-signature, downloadable new-hire PDF.
- Time tracking (`#/hr/time-entries`) — manager approve/reject workflow.
- PTO (`#/hr/pto`) — vacation/sick/personal policies, accrual rates,
  carryover caps, request/approve workflow with balance auto-deduction.
- Deductions (`#/hr/deductions`) — 401k, health, HSA, union dues
  per-employee with pre/post-tax classification and effective dates.
- Garnishments — court-ordered orders with priority rules and
  25%-of-disposable-earnings cap.
- Tax forms (`#/hr/tax-forms`) — W-2, W-3, Form 940 (FUTA), Form 941
  (FICA) endpoints returning JSON (WeasyPrint PDF rendering is pending).
- Employee self-service portal (`/portal/{token}`) — pay stub view, W-4
  updates, direct-deposit setup, PTO requests via per-employee token URL.

### Security hardening
- App-level `HTTPSRedirectMiddleware` + HSTS (2-year, includeSubDomains,
  preload) when `FORCE_HTTPS=true`. Session cookie carries `Secure` flag
  in the same conditional.
- `Content-Security-Policy` header — `frame-ancestors none`, `object-src
  none`, `form-action self`, Stripe origins allowlisted.
- Startup fail-hard checks (production only): refuses to start if
  `PAYROLL_ENCRYPTION_SECRET` is the dev default, `DATABASE_URL` lacks
  `sslmode`, or `FORCE_HTTPS=false`.
- Portal tokens now have a 1-year hard expiry and a 90-day sliding idle
  window (rolled forward on every authenticated request). Expired tokens
  return `410 Gone`.
- Portal pages emit `Referrer-Policy: no-referrer` and
  `Cache-Control: no-store` so the URL token doesn't leak via the
  `Referer` header or shared caches.
- Field-level encryption (bank routing/account numbers) now stores
  ciphertext with a `v1:` version prefix. `PAYROLL_ENCRYPTION_SECRET_PREV`
  env var supports zero-downtime key rotation.
- Per-IP rate limiting on every portal endpoint (30/min GET, 10/min POST),
  joining the existing 5/min on login.

### Docs
- Reorganized docs under `docs/`. Root keeps only `README.md`,
  `INSTALL.md`, `SECURITY.md`, `CHANGELOG.md` (the conventional set).
- New: `docs/security-hardening.md`, `docs/wiring-audit.md`,
  `docs/payroll-hr-module.md`.
- Stripped Phase N / Tier N scaffolding from the README — that history
  now lives here in the changelog instead.

## [2.0.0] — May 2026

### Added
- **Analytics dashboard** at `#/analytics` — KPI cards plus four charts
  (12-month revenue line, expenses doughnut, A/R+A/P stacked bar,
  90-day cash forecast), MTD/QTD/YTD period selector, CSV/PDF export
  with branded headers.
- **AI Insights** — Optional one-shot executive brief (3 observations /
  3 risks / 3 recommendations) with seven supported providers (xAI Grok,
  Groq, Cloudflare Workers AI, Cloudflare self-hosted gateway, Anthropic
  Claude, OpenAI, Google Gemini). Bring-your-own-key, encrypted at rest.
- **AI Predefined Analyses** — 11 curated actions across 5 categories,
  replacing the earlier free-form chat (more reliable across providers).
- **Inventory ledger** — Perpetual inventory with weighted-average cost,
  automatic COGS journal entries on every sale, reorder points,
  Adjust modal for add/remove/set-to-count.
- **Drill-down reports** — P&L and Balance Sheet rows are click-through
  to source transactions with running balance and source-doc links.
- **Saved Reports** — Name and one-click rerun favorite report configs.
- **Duplicate detection** — Fuzzy matching on customer/vendor names with
  a confirm-and-create-anyway dialog.
- **Setup wizard** collects operator name + email + company name + email
  + password (was password-only).
- **Branded headers** on PDF/CSV exports (SlowBooks Pro 2026 wordmark +
  company logo).

### Changed
- AI provider config moved from a modal to a Settings sub-page with a
  curated model dropdown and Custom escape hatch.
- Items form gained the full inventory toolset (track checkbox, qty,
  reorder point, asset account).
- Customers/Vendors gained the duplicate-warning confirm dialog.

### Security
- **Single-user authentication** — Argon2id-hashed password, session
  cookie (`same_site=strict`, 30-day TTL).
- **Rate limiting** — slowapi at 5 logins/minute per IP.
- **Security headers** — X-Content-Type-Options, X-Frame-Options DENY,
  Referrer-Policy, Permissions-Policy on all responses.
- **CORS lockdown** — explicit origin allowlist, no wildcards.
- **Path traversal protection** — backup and attachment endpoints use
  `Path.is_relative_to()`.
- **Atomic secret writes** — session key uses `mkstemp` + `os.replace()`.
- **Fernet encryption** for AI provider API keys.
- **SSRF protection** — AI provider URLs validated against private IPs
  and metadata endpoints.
- **Constant-time secret compare** in the Cloudflare Worker gateway.
- **Schema-validated AI config payloads.**
- **CSV formula injection protection** — exports neutralize `=`, `+`,
  `-`, `@` cell prefixes.
- **Non-root Docker** — container runs as UID 1000.

### Performance
- Analytics dashboard: 10 SQL queries, ~26 ms engine on 3,000 invoices
  plus 1,500 bills.
- Test suite runs in under 30 seconds with zero network dependencies.

### Fixed
- Dark mode now works on every report subtotal row (missing `--gray-50`
  definition).
- `--text-main` typo fixed.

## Earlier releases

Internal build history before v2.0.0 lived under "Phases" 1-11. A
recap of what each phase covered:

| Phase | Scope |
|-------|-------|
| 1 | Foundation — audit log, full-text search |
| 2 | Accounts Payable — POs, bills, bill payments, credit memos |
| 3 | Productivity — recurring invoices, batch payments |
| 4 | Communication & Export — CSV import/export, uploads |
| 5 | Advanced integration — bank import (OFX/CSV), tax export, backups |
| 6 | Companies, employees, payroll |
| 7 | Online payments (Stripe) |
| 8 | QuickBooks Online sync |
| 9 | Analytics + journal entries + deposits + credit-card charges + checks |
| 9.5 | AI Insights layer |
| 9.7 | Single-user authentication, rate limiting, security audit pass |
| 10 | Bank rules, budgets, attachments, email templates |
| 11 | Inventory ledger, drill-down reports, fuzzy duplicate detection, saved reports |

The payroll/HR module was layered separately:

| Tier | Scope |
|------|-------|
| 1 | Onboarding checklists, time entries, PTO |
| 2 | Deductions, garnishments, gross-up calculator |
| 3 | Tax forms (W-2/W-3/940/941), employee self-service portal |
