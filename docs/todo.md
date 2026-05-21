# TODO / Working Notes

Internal scratchpad for things we know we need to do but haven't shipped
yet. Not user-facing — the README and CHANGELOG don't link here on
purpose. When something on this list lands, move it to `CHANGELOG.md`
under `[Unreleased]` and delete it from here.

---

## Payroll / HR

### Tax form PDFs (the big one)
The W-2, W-3, Form 940, and Form 941 endpoints currently return JSON.
The SPA buttons in `#/hr/tax-forms` blob-open the response, so the user
sees raw JSON in a new tab instead of a printable form.

What's needed:
- WeasyPrint templates that match the IRS form layouts. The existing
  `app/templates/w2.html`, `form_940.html`, `form_941.html` are scaffolds
  but don't match the actual government boxes/grid.
- Either:
  - **Option A**: render to PDF server-side, set `Content-Type:
    application/pdf`, the existing JS `_openPDF` helper works as-is.
  - **Option B**: keep JSON, add a separate `/pdf` variant per endpoint
    (`/api/payroll/forms/w2/{emp_id}/pdf?year=...`) and have the SPA hit
    that for the print button. Lets the JSON stay machine-readable for
    future e-file integration.
- Prefer Option B — keeps the JSON contract clean for downstream
  consumers, PDFs become a separate concern.

### Other pending items
- **Portal cookie-based session** — Set a cookie on first
  `/portal/{token}` visit and redirect to a tokenless URL. The
  `Referrer-Policy: no-referrer` + token expiration cover most of the
  leak surface, but a cookie-based flow would eliminate the token from
  URLs entirely.
- **State unemployment filings (SUI)** — `app/services/tax_forms/state_sui.py`
  has the scaffolding; needs per-state form rendering.
- **E-Verify integration** — the schema has `everify_case_number` but
  there's no submission flow.
- **PTO carryover at year-end** — accrual balances don't auto-cap or
  zero out at year boundaries.
- **Pay run integration with time entries** — approved time entries
  should auto-populate the pay-run hours instead of needing manual
  entry.

---

## Security / ops

- **CSP off `'unsafe-inline'`** — once the bootstrap `<script>` block in
  `index.html` moves to an external file, we can drop `'unsafe-inline'`
  from `script-src` and tighten to a nonce-based CSP.
- **Encryption key rewrap migration** — we support
  `PAYROLL_ENCRYPTION_SECRET_PREV` for in-flight rotation but never wrote
  the offline `python -m app.services.encryption rewrap` command
  referenced in the encryption module docstring.
- **Portal access audit log** — every successful portal access already
  rolls `portal_token_last_used`, but a dedicated audit row per request
  (with IP, user-agent) would make incident response easier.
- **Pen test against a staging deploy** — never done.

---

## Frontend

- **Tax forms UI** — the buttons fire but the response is JSON. Once the
  PDF endpoints land, no JS changes needed (existing `_openPDF` will
  Just Work).
- **Portal-token UI** — admin should see "Last used N days ago" and
  "Expires DATE" alongside the token. The backend returns `expires_at`
  on mint; the SPA doesn't display it yet.
- **PTO accrual editor** — there's no UI for `POST /api/pto/accruals`.
  Admins have to use curl. Either build the form or add a "Enroll all
  active employees in policy X" button on the policies page.
- **Drag-and-drop for document uploads** — current employee documents
  tab is a click-to-browse file picker only.

---

## Tests

- **Wiring audit can't catch typos cheaply** — the four disconnects we
  fixed were all caught by manual grep. A lightweight test that imports
  the FastAPI app and checks "every JS path appears in `app.routes`"
  would catch the next batch automatically.
- **WeasyPrint smoke test** — tests skip PDF assertions because rendering
  is slow. A single `test_*_pdf_renders_non_empty` per template would
  catch broken templates.
- **Portal flow end-to-end** — TestClient covers each endpoint, but no
  test walks the full token-mint → access → expire → rotate cycle.

---

## Polish

- **`.env.example`** — we document `PAYROLL_ENCRYPTION_SECRET`,
  `FORCE_HTTPS`, etc. in `docs/security-hardening.md` and SECURITY.md
  but there's no example env file to copy.
- **Docker Compose for production** — `docker-compose.yml` is dev-only;
  no prod-ready compose with nginx + TLS + the env vars set.
- **Branded portal favicon** — currently inherits the SPA favicon.
  Could fall back to the company logo when set.

---

## Known small bugs

- `tax_forms.js` opens the JSON-mode response as `blob:` — the new tab
  shows raw JSON instead of nothing useful. Not broken, just confusing
  until PDFs ship.
- Pay-stub PDF doesn't show negative deductions correctly (off-cycle
  reimbursements come through as positive line items).
