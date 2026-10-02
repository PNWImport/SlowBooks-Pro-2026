# Changelog

Notable changes between releases. Format roughly follows
[Keep a Changelog](https://keepachangelog.com/). The internal build order
used during development is captured here so the README can stay focused
on what the software does, not on what sprint shipped what.

## [Unreleased]

- ACH File button on processed pay runs: downloads the NACHA direct-deposit
  file from `/api/payroll/{id}/nacha`. The endpoint existed but had no UI.
- Every payroll and tax document names the company from Settings (company
  name and EIN), instead of placeholder text.
- The ungated-endpoint guard unwraps included routers, so the "no endpoint
  without login" test checks every route again instead of silently passing.
- Company ACH details are saved encrypted, behind a per-user access flag,
  with a masked view and a password prompt to show full numbers.
- Refuse migration journal references over 100 characters before posting, preventing inconsistent replay identity handling across database backends.

Target version: **2.18.0**, following upstream 2.17.3. These branch changes are not yet released.

- Incorporate upstream through `90ba2b7` (2.16.2–2.17.3): payments, credits and
  bill payments refuse other parties' documents with named messages; invoice
  edits post through the create path; duplicates recompute tax from the customer;
  OpenAI reasoning models get `max_completion_tokens` and no temperature; money
  columns widen to Numeric(15, 2), with a local join migration that also widens
  this branch's payroll columns.
- Fix every recomputing invoice edit returning 500 after the upstream intake
  (`assert_not_reconciled` now takes the session on this branch).
- AI: Claude 4.7 and later (every Claude 5 model, including the default) are no
  longer sent a temperature, which their API refuses with a 400. Bundled models
  add `claude-opus-5-5`, `claude-fable-5-1`, `gpt-6-sol`, `gpt-6-luna`,
  `chat-latest` and `grok-4.7`. Ask SlowBooks sends GPT-6 Sol/Luna
  `reasoning_effort: "none"` (the only setting at which Chat Completions allows
  their tools) and refuses GPT-6 Astra, whose tools require the Responses API.
- Dependencies: uvicorn 0.54, starlette 1.7, alembic 1.20, PyJWT 2.15,
  psycopg2-binary 2.9.13, python-dotenv 1.2.3 and current transitive packages;
  vendored Chart.js 4.5.1 (npm registry integrity verified). SQLAlchemy stays
  below 2.1 and ruff below 0.7 deliberately.
- CI: every action pinned to a release commit SHA at its current major
  (checkout 7, setup-python 7, setup-node 7, upload-artifact 7,
  download-artifact 8, github-script 9, codeql-action 4, azure/login 3,
  softprops/action-gh-release 3); Trusted Signing moves to its renamed
  `azure/artifact-signing-action@v2` with `signing-account-name`; macOS jobs
  move off `macos-14` (unsupported from November 2, 2026) to `macos-15`.
  Dependabot now proposes weekly pip, Actions and Docker updates.
- Kubernetes: the migrate Job ran `/bin/bash`, which the Alpine image lacks,
  and waits for Postgres instead of spending its retries; the bundled Postgres
  speaks TLS (the Secret's `sslmode=require` refused every connection); app
  probes no longer follow the FORCE_HTTPS redirect into a TLS handshake the pod
  does not serve. All pods run non-root with seccomp RuntimeDefault, no
  privilege escalation, dropped capabilities and read-only roots; postgres runs
  as the Alpine image's uid 70; images are tagged, not `latest`. New
  NetworkPolicies deny ingress by default and open only ingress → app,
  app/migrate → Postgres and app → Redis. Verified on a kind cluster.
- CI hygiene, verified by running the workflow locally under `act`: fix a
  parent-watcher test that assumed a PID-1 process reaper `act`'s container
  doesn't provide; skip the coverage-artifact upload step only under `act`
  (`upload-artifact@v7` isn't yet supported by its artifact server); isolate
  test-generated uploads/backups from the real `app/static/uploads` and
  `backups/` directories via `SLOWBOOKS_DATA_DIR`; stop 151 money-typed model
  and schema fields from serializing a bare `int`; make
  `reconciliation.completed_at` timezone-aware; update Alembic's renamed
  `path_separator` config key; adopt `httpx2` for Starlette's `TestClient`;
  replace legacy `Query.get()` with `Session.get()`; close five leaked SQLite
  engines in `test_schema_repair.py`. Full suite: 4,968 tests, 0 failed,
  0 errors; CI test job under `act`: 4,952 passed, 0 failed.

- Serialize migration imports before duplicate/opening-balance checks on both
  PostgreSQL and SQLite; overlapping imports must not double-post journals.
- Reserve SQLite writes before reconciliation's open-session check so two
  simultaneous starters cannot create duplicate open reconciliations.

- Incorporate upstream through `a1022f8`: recognize Wave full-export debit/credit
  headers, refuse all-zero ledgers, count skipped journals, and skip previously
  imported transaction references and synthesized opening balances.

- Refuse schema-repair retry drops unless a pending migration creates the
  blocking table; preserve unrelated empty tables when upgrades fail.

- Incorporate upstream through `80f2ad8`: year-to-date P&L and balance-sheet
  trend cards, current-month date boundaries, live chart theme redraws,
  nonprofit phrase casing, and desktop permission-denial regressions.

- Make chart replacement atomic on invalid input; bind apply to the reviewed
  plan and current chart; preserve bank/type invariants; apply parent-only
  changes; and reject cyclic account hierarchies.

- Reject missing parents and indirect cycles in ordinary account edits, including
  concurrent PostgreSQL/SQLite edits; escape diagnostic error text to prevent forged
  log lines while retaining traceback details.

- Use the supported Alpine runtime image with the PDF/OCR/PostgreSQL toolchain,
  and remove build-only pip from the final image; expand CI formatting/lint
  checks to packaging and migrations and run all frontend tests.
- Clean up failed server database dumps and preserve safe backup retention when
  paths contain spaces.
- Safely handle absent upload filenames and retry/exception paths in accounting
  imports and recurring invoice creation.
- Make missing-record and malformed-artifact boundaries explicit in payroll,
  reconciliation, nonprofit reporting, IIF imports and audit verification.
- Reject fractional cents consistently across operator-entered accounting and
  payroll amounts while preserving the separate precision of quantities, tax
  rates, exchange rates and inventory calculations.
- Prevent bill and batch-payment allocations from settling documents owned by
  another vendor or customer, and reject nonpositive allocations.
- Prevent deposits from exceeding available Undeposited Funds and serialize
  concurrent deposit posting against that balance.
- Reverse invoice inventory and COGS from recorded movements and journal lines,
  preserving historical costs and accounts after quantity edits or item-setting
  changes.
- Reject fractional-cent customer/vendor credit applications, and reverse
  recorded inventory movements when voiding bills or credits even if an item's
  inventory tracking setting has changed since the document was created.
- Return desktop sign-out to the company picker, list active usernames before
  sign-in, and open the last company automatically until the picker is chosen.
- Preserve parked accountant-sharing and Canada plans as explicitly noncommittal
  design notes, indexed alongside the repository's shipped design records.
- Remove obsolete QuickBooks storage-internals provenance from code comments
  and describe the application as an independent replacement.
- Repair Wave Account Transactions imports and add a Copy action for newly
  created API tokens; retain the real-file and workflow attribution in tests.
- Keep attachment downloads ahead of dynamic routes, make generic hidden state
  effective, and restore Quick Entry log contrast across themes.
- Add vendor credits with application/void workflows, AP/AR aging parity and a
  joined migration path; safely repair half-upgraded SQLite and PostgreSQL only
  after proving blockers and dependent children are pending-created and empty.
- Preview saved and unsaved invoice-email templates through the same sandboxed
  renderer used to send them, with secret redaction and actionable blank-variable
  notes; show the invoice dialog preview in a sandboxed iframe as its note changes.
- Add Windows portability CI with per-test timeouts and avoid the macOS HarfBuzz
  collision by excluding Pillow font modules before bundle analysis.
- Apply company vocabulary to server messages and AI labels while composing
  ledger/payment references from each document's own face.
- Keep the generic AI provider's required model field visible and browser-
  bounded on first selection, and identify both self-hosted and custom endpoints.
- Give Windows installations without WebView2 an actionable runtime/installer
  message and optional loopback browser fallback; keep the server timer default
  unless an explicit resolution is configured, with matched cleanup.
- Release closed event loops retained by anyio's test registry and make
  Windows-sensitive source assertions read UTF-8 explicitly.
- Import Bank of America detail CSVs with bounded header discovery, balance-row
  exclusion and deduplication; show import progress and restore buttons on failure.
- Retry transient macOS signing timestamp failures only; include commit identity
  in the macOS bundle so builds of one release can be distinguished.
- Embed app-version metadata in Windows executables and reject missing or
  incorrect metadata before signing the build.
- Keep headless/smoke launches from changing the desktop's selected company,
  while preserving LAN TLS enforcement; sanitize URL-parser and scan-image errors.
- Add native Windows/macOS PDF receipt rasterization with Poppler fallback and
  renderer status in Settings; keep library/process errors out of responses.
- Correct cash-flow reporting to follow bank-kind cash journals, excluding
  non-cash activity, internal bank transfers and opening carry-forwards.
- Claim bank-review batches before processing and leave busy postings unchanged
  for retry instead of waiting with conflicting statement/ledger locks.
- Repair Banking source-document links and legacy Check Register navigation;
  reject manual matches to voided entries and refresh locked ledger lines before
  allowing expense or journal voids against reconciliation state.
- Revalidate automatic bank-match candidates before linking, and refresh locked
  reconciliation state before matching or unmatching a statement line.

### Accumulated branch changes

- Allow QBO OAuth callbacks without a session cookie while retaining state
  validation; hide provider errors from callback responses (upstream `7c0d274`).
- Sanitize QBO/IIF route and per-row failures without leaking provider, SQL or
  driver payloads; retain authored IIF validation messages and row rollback.
- Redact stored credentials from editable donor acknowledgment subjects and
  bodies, sharing the settings API's secret registry (upstream `2fd6758`).
- Initialize new PostgreSQL companies with migrations and seeded accounts,
  not just empty tables; do not register failed initialization attempts
  (upstream `dba2839`).
- Keep PostgreSQL backup failure details in server logs instead of exposing
  raw tool output in API responses.
- Recalculate estimate totals when only the tax rate changes; preserve
  due-on-receipt terms and job/cost attribution when converting estimates.
- Reject nonpositive and cross-customer credit applications, and require an
  original invoice reference to exist and belong to the credit memo customer.
- Preserve credit-memo job attribution in original postings and use shared
  due-on-receipt terms semantics when creating bills.
- Duplicate invoice sale lines without carrying over separately assessed late
  fees, preventing an unbalanced-journal error after late fees were applied.
- Attribute late fees to the invoice's job and reverse their separate postings
  when voiding the invoice, retaining each fee's posting date and accounting tags.
- Preserve original job, class, cost and functional tags when voiding invoices,
  so the reversal also cancels the amounts in dimension-specific reports.
- Carry duplicated invoice cost codes into journal lines as well as document lines.
- Preserve job and line-level job/class attribution when duplicating invoices,
  including the journal entry, plus line cost codes and tax-exempt flags;
  use the shared terms parser so duplicated
  due-on-receipt invoices remain due that day.
- Use canonical Decimal rounding for check amount words, carrying rounded cents
  into dollars and placing negative signs on the amount rather than the cents.
- Repair the adjacent preceding benefit-rate interval when deleting a dated
  rate, preserving explicit expiry dates, intentional gaps, and later rates.
- Reject duplicate group benefit codes with a conflict response before replacing
  existing assignments, instead of raising a database integrity error.

- Skip repeated customer, vendor, and item names within a single CSV import.
- Preserve QBO mapping dependencies during exports and inactive/non-taxable
  flags during imports; avoid applying historical payments twice to invoices.
- Keep negative income negative in AI profit summaries and apply the requested
  tax-summary date range to expenses as well as invoices.
- Reject malformed/non-finite FX responses and clean up temporary session keys
  when persistence fails.
- Reject cross-customer IIF payment allocations and deduplicate payments whose
  customer label includes a job suffix.
- Reject missing journal accounts and non-finite amounts before journal creation.
- Exclude voided payments from downloaded and batch-emailed customer statements.
- Escape names in statement/collection emails and retain Decimal precision when
  summing collection balances and income-by-customer totals.
- Handle malformed AI response envelopes and non-text content without leaking
  parser exceptions or returning objects where text is required.
- Handle malformed OCR intake timestamps safely and normalize explicit timezones
  before receipt expiry checks.
- Bind OCR intake metadata to its own receipt ID and filename so malformed
  expiry records cannot delete a different receipt.
- Upsert repeated budget keys within one batch and reject invalid months.
- Fix valid dates being rejected when recording sales tax payments; expand schema collision checks.
- Refreshed AI defaults, made every model ID editable, and completed custom-endpoint validation and wiring.
- Pin Custom and Worker AI connections to the public address approved by the SSRF guard.
- Refresh saved onboarding, employee, and pay-schedule changes; suppress duplicate terminations, close active coverage, and keep new plans on Benefit Coverage.
- Fix container keys, Compose parsing, HTTPS health checks, and rate-limit defaults; existing installs must preserve their settings key before upgrading.
- Run Docker and Kubernetes app containers non-root with read-only roots and no Linux capabilities; repair Docker upload/backup volume ownership before startup.
- Expanded payroll, HR, benefits coverage, and filing helpers.
- Add guarded contractor-run voids with reversing entries and ACH warnings.
- Correct federal deposit holidays, semiweekly extensions, quarter splits, and $100k allocation/carryover.
- Shift pay dates around bank holidays/blackouts and keep assigned employee frequencies in sync.
- Add employee time-entry submission to the portal, enforce workflow/hour bounds,
  serialize payroll/job consumption, and fix Documents route precedence.
- Serialize accounting process/void/conversion, PTO, and HR transitions,
  restrict journal voids to one manual reversal, and scope reconciliation toggles.
- Signed audit checkpoints and additional PII protection.
- Prevent lost account-balance updates during concurrent journal/invoice writes;
  serialize document-audit appends and commit signatures with their audit rows.
- Preserved both benefits systems and reconciled upgrade paths.
- Hardened uploads, audit redaction, startup checks, and backup/restore.
- Revalidate signed-in accounts; require LAN HTTPS and restrict Windows server privileges/access.
- Unified PDF rendering and excluded local secrets/data from Docker builds.
- Corrected CT/MN paid-leave caps; added regression and migration checks.
- Bound high-growth transaction lists and eliminate N+1 loads for time/job,
  journals, recurring invoices, payables, payroll benefits, and remittances.

### v2.17.3 — Payments land on the right account

**Pay Bills paid one vendor's bills with another vendor's payment.** The
screen lists every vendor's open bills, and sent all the ticked bills as one
payment to the first bill's vendor. On the QA company, ticking a CPA's bill
and a supplier's recorded one 5,638.26 payment to the CPA that also marked
the supplier's bill paid; the vendor balances, the check register and the
1099 figures were all wrong from then on. Pay Bills now makes one payment
per vendor, and asks you to pay one vendor at a time when you enter a check
number, since one check cannot pay two vendors.

**A payment pays down its own customer's or vendor's documents only.** A
customer payment could be applied to another customer's invoice (#189,
@Bit-Sage), and the same was true of applying a credit memo, a batch payment
line, and a bill payment to another vendor's bill. Each returned success and
reduced the other party's balance. All four now refuse with a message naming
the document and write nothing; a batch with one wrong line is refused whole.
Vendor credits already checked this.

If you paid several vendors at once from Pay Bills in an earlier version,
check Vendor Balances: a payment may be recorded against the first vendor
for bills that belonged to others. Void it and pay each vendor separately.

No schema change.

### v2.17.2 — Editing an invoice keeps its job costing

**Saving an invoice from the edit screen stripped its job costing.** An edit
rebuilt the invoice's ledger entry by a separate route from creating one,
and that route dropped the job, class and cost code from every line of the
entry; the invoice form, which has no cells for them, never sent the
per-line values back either. Revenue quietly left the job-cost reports each
time an invoice was saved. On the QA company, re-saving all 960 invoices
unchanged took their ledger lines from 565 job and 875 cost-code tags to
none. Both halves are fixed: an edit now posts through the same code as a
new invoice (#187, @Bit-Sage), and the form sends each line's job, class
and cost code back. The same 960 re-saves now keep all 565 and 875, and the
trial balance does not move.

Where it showed: **Job Cost Detail**, which splits a job's revenue by cost
code — one of the QA company's jobs went from seven cost codes to a single
*uncoded* line on 2.17.1. Job Profitability, which files a line under the
invoice's own job when the line has none, kept reading correctly for
invoices that carry their job on the header, which is why the loss was easy
to miss.

**An edited invoice posts the way a new one does** (#187). A foreign-currency
invoice's edit posts at its exchange rate — it posted document-currency
amounts to the home ledger before; changing the invoice date moves its
ledger entry with it, subject to the closing date; and a total can no
longer be edited below what has already been paid. Paid and partly-paid
follow the payments.

**API.** `PUT /api/invoices/{id}` with `status: "void"` is refused with a
message naming `POST /api/invoices/{id}/void`; an empty `status` is refused;
a requested `paid` or `partial` on an invoice whose payments say otherwise
is not applied.

No schema change.

### v2.17.1 — OpenAI works again

**AI analysis with OpenAI failed on current models** (#185, @Sciumo). OpenAI's
reasoning models — the gpt-5 line, including SlowBooks' default
`gpt-5.4-mini`, and the o-series — refuse `max_tokens` and any temperature
but their default, so the request was rejected before it ran, the Test button
included. OpenAI is now sent `max_completion_tokens`, and no temperature for
its reasoning models. Grok, Groq, Cloudflare and custom endpoints send what
they always sent.

**Room to think.** A reasoning model spends hidden reasoning out of the same
token budget as its answer, so the 1,024 tokens that suit every other
provider could run out before the answer began. OpenAI's reasoning models get
a ceiling of 8,192 — billed only as used — and a reply that stops at the limit
with nothing written now says so, instead of "empty response (body shape
unexpected)".

No schema change.

### v2.17.0 — Your ledger, in a spreadsheet

**Trial Balance and General Ledger save as a spreadsheet and a printable
file** (#179, @cnbarry1); Profit & Loss and Balance Sheet, which already
printed, gain the spreadsheet. Each report has *Save CSV* and *Save PDF*
buttons. The files hold the figures on the screen: the trial
balance with debit, credit and net per account and totals that agree; the
general ledger with every posted line, a balance brought forward, a running
balance, the kind of document each line came from, and a period total per
account whose net equals that account's trial balance line. Balances read
in each account's natural sign, the way the balance sheet shows them: an
asset or expense is debit minus credit, a liability, equity or income account
credit minus debit, so a payable you owe and income you earned read positive.
Amounts are
written as plain numbers, so a spreadsheet sums them without a conversion
step; text cells keep the formula guard every other export has. The on-screen
general ledger gains the same running balance and brought-forward row.
Exporting reads the books and writes nothing.

**Bank feeds from any SimpleFIN provider** (#181, @cnbarry1). SlowBooks has
always followed the claim URL inside a setup token, wherever it points, as
long as it is HTTPS and not a private or local address; the Banking page and
the setup guide named only bridge.simplefin.org. They now say any SimpleFIN
provider works.

No schema change. An existing company file opens with no upgrade step.

### v2.16.3 — The Docker image starts again

**A freshly built Docker image failed to start.** SQLAlchemy 2.1.0, released
this week, makes a plain `postgresql://` address use the psycopg 3 driver; the
image installs psycopg2, so the app could not import and the container exited.
Anyone building the server or Docker install from scratch since the release
was affected, on 2.16.1 and 2.16.2 alike. SQLAlchemy is pinned below 2.1, the
version every release has been tested on; moving to 2.1 will be its own
release. v2.16.2 was tagged past the red check that showed this — a miss in
the release process, and the Linux QA lane now builds the image from nothing
every time.

The desktop apps use SQLite and are unaffected by the Docker fault.

**The What's New box on the splash reads in the dark theme.** It had the
light panel the licence block had before 2.15.0 and was never given a dark
one: 2.34 : 1 in dark, now 11.95 to 15.23, measured in a rendered browser.
Found by the macOS lane and reproduced at the window by the owner.

No schema change.

### v2.16.2 — Tax-exempt customers, wider amounts, and two forms put right

**The estimate's line items line up with their headings** (#176, @cnbarry1).
The header read Item, Description, Cost code, Cost, Qty while the cells
underneath ran Qty, Cost code, Cost — so the quantity sat under *Cost code*
and the cost code under *Cost*. The cells follow the header now; picking an
item fills its standard cost as the line's cost, blank if it has none and
yours to overwrite; the item select keeps a readable width; and the form
opens wide, its table scrolling sideways when the window is narrower still.

**The Job Cost Entry dialog shows all of its cost lines** (#174, @cnbarry1).
Eleven columns in a 700-pixel dialog whose table hid its overflow: the
Bill? column and the remove button were cut off with no way to reach them,
and the selects had shrunk to a few characters. The dialog opens as wide as
the window allows, the table scrolls sideways when that is still not enough,
and every control keeps a readable width. Any dialog with a wide table can
ask for the same with `openModal(title, html, { wide: true })`.

**Hosting your own books on a cloud server has a guide**, `docs/cloud-hosting.md`
— one VPS, Docker, a proxy with a real certificate, backups off the box, and
what the setup does and does not give you. On the way, the production
compose file now passes `TRUST_PROXY_HEADERS` into the container, so the
proxy trust the TLS guide describes takes effect under Docker.

**A customer marked non-taxable pays no sales tax on any line.** The
exemption only filled lines that left their tax flag unset, and every sales
form sends each line's Tax box, defaulted from the item — so a reseller or
exempt customer billed from the window was charged tax. Invoices,
estimates, recurring templates and sales receipts all honour the customer
now, and the forms clear and disable the Tax boxes and say why. Found by
the Windows lane on this release's gate. Documents already saved keep the
tax they were saved with; check any open invoice to a reseller.

**A new document built from an old one gets the customer's current tax.**
Converting an estimate, duplicating an invoice and running a recurring
template copied the source's stored tax, so a reseller estimate saved before
this release became a new invoice billing tax and crediting Sales Tax
Payable. All three now compute the tax from the customer as they stand
today. Found by the Windows lane on this release's gate, on an upgraded file.

**The estimate screen shows the tax it will charge.** It taxed the subtotal
on screen instead of the ticked lines, so an unticked Tax box — for any
customer — still showed tax before saving; the saved estimate was always
right. It reads the same as the invoice screen now (macOS lane, this gate).

**The licence link on the splash reads at AA in the light theme** (4.29 : 1
before, 5.44 now, measured in a rendered browser). The dark theme's licence
block, fixed in 2.15.0, measures 7.23 to 15.23.

**Money columns hold up to 9,999,999,999,999.99** (#173, @6lb). Every
amount column widens from 12 to 15 digits, for currencies whose everyday
amounts are large — 9,999,999,999.99 dong is about US$400,000. Rates,
quantities and exchange rates are unchanged.

**Schema change:** one migration widens the money columns. The desktop app
and the Docker image apply it when a company file opens; a self-managed
server runs `alembic upgrade head`. Nothing is converted — the stored
amounts are the same numbers in a wider column.

### v2.16.1 — Wave's full export imports its journals

**Wave's full export imports its journals** (#169, @rcavatar1-debug). Wave's
"Get all transactions" file heads its sides *Debit Amount (Two Column
Approach)* and *Credit Amount (Two Column Approach)*; neither was recognised,
so every line read 0.00, the dry run said "14,372 journals ready to import",
and the import wrote none of them. The same file's *Amount (One column)* is
signed by what it does to the account, not by side, and is no longer read as
"positive = debit" when the file has its own debit and credit columns.

**A ledger whose amounts all read zero is refused, by name.** 0 = 0
balances, so an unrecognised amount column passed the dry run and imported
nothing — the hole behind this report and behind 2.11.1's Wave fix before it,
which fixed the headers and not the hole. The dry run now fails with the
file's own header row in the message, for every migration source; a few
amount-less journals among real ones are a warning and are counted as
skipped in the import result.

**A second click on Import does not double the books.** Nothing stopped a
repeat import from posting every journal again. A journal whose transaction
id an earlier import from the same source already posted is skipped; the dry
run says how many, the result carries `duplicate_journals`, and a later
export with new transactions imports only the new ones. The synthesized
opening-balance journal is likewise posted once.

No schema change. An existing company file opens with no upgrade step.

### v2.16.0 — The year at a glance

**Two new overview cards, both opt-in** (#166, @jarvis4openclaw): *P&L: Year to
Date* — income, expenses and net for the year with cumulative net by month —
and *Balance Sheet Trend* — assets, liabilities and equity at each of the
last twelve month-ends, the current month to date, as a line chart. The trend
folds current net income into equity the way the Balance Sheet report does,
so it balances at every point and its latest point equals the report. Pick
them under Customize; neither is in a default layout. A nonprofit sees
Activities, Statement of Financial Position and Net Assets.

**The chart import dialog offers a CSV template** (#164), the same file the
site hands out, served by the app so an offline install has it.

**A lower-case word takes a wholly lower-case phrase.** A nonprofit's card
description read "liabilities and net Assets": the vocabulary swap lowered only
the first letter of a multi-word replacement. Found on this release's gate; the
server's swap and the page's carry the same rule.

**A theme toggle redraws the charts on screen.** Canvas ink is painted with the
theme that was active when the chart was made, so toggling the theme with the
Balance Sheet Trend on screen left light-mode axis text on a dark panel
(1.06 : 1) until the next visit; the Analytics page had carried the same flaw
since it shipped. Found by the Windows lane on this release's gate.

No schema change. An existing company file opens with no upgrade step.

### v2.15.0 — Your chart, from your file

**Import a chart of accounts** (#139, #161, @tresero). Chart of Accounts →
Import… reads the application's export columns, a spreadsheet with Number /
Name / Type, or hledger account-list output. The first pass is a dry run;
the second applies the reviewed plan. Existing accounts match by number then
name, and control accounts are renamed in place instead of duplicated.
*Replace the seeded chart* deactivates only unused, unmentioned accounts.

Parent-only hledger segments that name a control account now reuse that
control account, and re-importing an unchanged file is a no-op.

### v2.9.3 — SimpleFIN request pinned to the address the guard approved

**One security fix, right behind 2.9.2.** The SimpleFIN SSRF guard resolved
the bridge hostname and refused private addresses, then the HTTP client
resolved the name again to connect — a second DNS answer could steer the
socket at a private service (DNS rebinding; CodeQL py/full-ssrf, #104,
raised on the 2.9.2 pull request and wrongly dismissed as guarded). The
request now connects to the address the guard checked, with the hostname
kept for the Host header and TLS (the certificate is still verified against
the hostname), and a response from a non-global peer is discarded.

### v2.9.2 — Security: HR and payroll are admin-only; payment row locks; Server Edition CSP; SimpleFIN on PostgreSQL

**Security (Server Edition).** Four private reports arrived on the same
morning, three from @hongshengy and one from @furkan-arslan-sec, and all four
were right. The role gate treated everything outside six admin prefixes as
"daily books", so a bookkeeper could mint any employee's self-service portal
token (a full login as that employee: W-4, bank accounts, pay stubs), rewrite
any employee's direct-deposit account and export the NACHA file, and a
read-only user could download pay stubs, W-2s and I-9 paperwork. The docs
said HR and payroll were admin functions; the code now agrees: payroll,
tax forms, benefits, garnishments, onboarding, and the credential-bearing
parts of an employee record (portal token, bank accounts, documents,
E-Verify, year-to-date) are refused to bookkeeper and read-only roles for
every method; creating or editing an employee is an admin write; the
employee list stays readable as a directory with pay, tax and address fields
blanked for non-admins. The SPA hides those pages for non-admins. Separately,
batch payments and bill payments now take the same row lock on the invoice
or bill that single payments already did, so two concurrent requests on
PostgreSQL cannot both pass the balance check and over-apply; an
over-application that slips past the check is refused with 409 instead of a
negative balance. Advisories GHSA-rh68-48w8-pj8r, GHSA-rh75-6834-f66j,
GHSA-pwj7-6qq3-h4fj, GHSA-rm5h-555g-vpjj; fixed in 2.9.2.

**Server Edition no longer serves the desktop's relaxed script policy to
LAN browsers.** The launcher marks every server it starts as "desktop",
including headless `--serve-lan`, so the `'unsafe-eval'` allowance the
native web view needs went to the whole office (found by Keith in the
post-release macOS review). The policy is now decided per request: relaxed
only when the launcher flag is set *and* the request arrived over
loopback, which is the only way the web view ever connects. **SimpleFIN
settings on PostgreSQL** — the settings table was created with a 500-
character value column that SQLite ignores and PostgreSQL enforces, and a
bank feed's access URL is longer than that; the column is now text
(contributed by @kycrna). **Bank feeds can target a liability account**,
so a credit card feed lands where the card lives (also @kycrna).

### v2.9.1 — Post-release tidy from the 2.9.0 gate

**A stored AI provider key can be removed.** `PUT /api/analytics/ai-config`
with `"api_key": ""` clears it (omit the field to keep it; a value replaces
it), the spec says so, and the Settings page has a Remove button beside the
saved-key mark — it no longer round-trips a blank field. **Windows releases
publish `SHA256SUMS.windows`** beside the installer and zip, the same
format as the macOS file, so a download can be checked without trusting
the transport. **The migrations now create every table** (`api_tokens` was
the last one only app startup made), so `alembic upgrade head` alone yields
the complete schema. Two nonprofit vocabulary leaks closed: the
Contributions by Donor card described "sales totals", and the analytics
receivables aging header said "Customer". The macOS maintainer runbook
describes the staple-before-DMG order that has shipped since 2.9.0, and the
install guide's table and account counts are current.

### v2.9.0 — Nonprofit mode

**A nonprofit sees its own words in the first minute.** Settings → Company
Type → Nonprofit swaps the vocabulary everywhere it shows: Customer → Donor,
Invoice → Pledge, Sales Receipt → Donation, Class → Fund, Job → Grant, Profit
& Loss → Statement of Activities, Balance Sheet → Statement of Financial
Position, Equity → Net Assets. One dictionary, applied at render, on screens,
in report titles, in PDF filenames and on the dashboard; nothing in the API
or the database changes name, and a business file renders exactly what it
did before. Printed documents are literal, not vocabulary: a donation prints
as DONATION RECEIPT, a pledge as PLEDGE, a program fee still as INVOICE.

**Net assets by restriction, without a closing entry.** A class is a fund
with a restriction (without / with donor restrictions, purpose or permanent)
and a default function. When a restricted fund spends for its purpose, a
**Release from Restriction** moves that much to net assets without donor
restrictions — one document, DR 3400 / CR 3300 tagged to the fund, with the
amount suggested from the fund's unreleased spending. The **Statement of
Financial Position** splits the change in net assets by restriction at
report time, the way the balance sheet already synthesizes net income, so
the two net-asset lines always add up to the balance sheet's equity; the
**Statement of Activities** shows revenue and expenses in two columns with
releases between them and its change in net assets is the P&L net income;
**Fund Balances** shows each restricted fund's beginning, contributions,
spending, releases, ending and unreleased. P&L by Class now groups on the
line's class first (a bill with three line classes and a blank header used
to land whole in Uncategorized), and every void reverses with job, class,
cost code and function carried.

**Every expense knows its function.** Posted lines carry program /
management / fundraising, defaulted from the fund. Shared costs — rent, the
office manager's wages — are posted unassigned and divided by a saved
**allocation rule** (percent, square feet, or hours on grants), either with
**Split** on the entry line or as a month-end **Functional Allocation** that
reclasses whatever is still unassigned on the rule's source account without
moving the P&L by a cent; running a month twice finds nothing to move. The
**Statement of Functional Expenses** puts every expense account in Form 990
Part IX columns, with the program-by-program breakout, as PDF and CSV.

**Donor documents.** A donation receipt prints the IRS Publication 1771
acknowledgment — the date, the amount, and either "no goods or services were
provided" or the fair value of the gala dinner with the deductible portion.
Every gift gets an **acknowledgment letter** (PDF and email) worded by the
editable `donation_acknowledgment` template with `{{ irs.text }}` supplied.
**In-kind gifts** are their own two-sided document (the piano to Musical
Instruments, the credit to In-Kind Contributions) acknowledged without a
stated value. **Year-end giving statements** list every cash gift with the
deductible portion and non-cash gifts without amounts — one donor, every
donor in one PDF with a page break each, or emailed to everyone who has not
opted out. The **pledge report** reads promised, invoiced, received, written
off and outstanding off recurring pledges and their installments (generated
invoices now remember their template and carry its grant), and a pledge that
will never be paid is **written off** through a credit memo to Bad Debt
Expense — credit memos gained the void they never had, which is also the
undo.

**Reports you can find and compare.** In the desktop app, Save PDF now
writes the report to Documents → SlowBooks Pro → Reports (period-stamped, never
overwritten), opens it, and says where it went with a Show-in-folder button —
it used to land in a temp folder. Saved report definitions are a collapsible
list at the top of the Report Center instead of a growing wall of cards. The
Statement of Activities and the Statement of Functional Expenses gained
"Compare to prior year": the same dates a year earlier as two more columns,
on screen, in the PDF and in the CSV.

**Riverbend Community Arts.** The stage's acceptance test is a seeded
nonprofit year — a grant, an endowment, a gala, pledgers, a piano, rent
split 70/20/10, a June release — driven entirely through the API with scoped
tokens the way a bring-your-own-AI agent would, checking that every
statement reconciles to the cent and that a readonly agent cannot write.
Design notes: [docs/design/nonprofit.md](docs/design/nonprofit.md); user
guide: [docs/nonprofit-module.md](docs/nonprofit-module.md).

**A custom AI provider** (contributed by @jarvis4openclaw): an eighth AI
Insights provider that points at any OpenAI-compatible chat endpoint on the
public internet, HTTPS-only and behind the same address guard as the Worker
gateway, with the model ID yours to type. Along the way it fixed the
self-hosted Cloudflare Worker gateway, whose replies had been parsed to an
empty string.

**From the release gate (SlowBooks-Pro-Testing, 2.9.0).** The macOS app is
now notarized and stapled *before* the disk image is built, so the copy a
user drags to Applications carries its own ticket and launches offline;
the bundle declares why it writes to Documents and Downloads, and a refused
folder is explained (the file goes to the app's data folder and the notice
says so) instead of failing like a crash. For agents driving the API: an
unknown request field is a 422 naming the field, never silently dropped;
`tax_rate` is documented as a fraction and a percent-looking value is
rejected with the unit in the message; `pto_type` and `accrual_method` are
enums in the spec; an empty pay run is refused with the roster named;
`DELETE` on a posted document names the `/void` route; a fresh company has
6810 Depreciation Expense and a default Equipment asset type so depreciation
runs first time; a missing `companies.json` is logged with the data
directory that was searched.

**Round 3 of the gate found the macOS desktop bridge dead — since v2.1.0.**
Save PDF, print preview, Save backup, Show in folder and the company picker
all rely on pywebview's `window.pywebview.api`, which pywebview builds with
`new Function`; the app's Content-Security-Policy had no `'unsafe-eval'`,
WebKit enforces that inside the page, and the bridge stayed empty on every
Mac while Chromium on Windows let it through. The policy now allows eval
only under the desktop launcher (a browser install keeps the strict one).
The shell also stops failing in silence: a missing bridge is reported on the
first click and checked at startup, Save CSV goes through the bridge to the
same Reports folder as Save PDF, and every export a desktop fetch receives
is served inline so neither webview swallows it as a download. Two more
from the same round: first-run setup on a file that already holds books now
says whose books they are and prefills the name, and the company name in
Settings keeps the manifest (the picker's name) in step so the two can no
longer diverge; the Windows installer clears `_internal` before an upgrade
so stale package metadata from earlier builds no longer ships.
Round 4 closed the loop on the name reconciliation itself: two company files
can never end up with one name — renaming a company (in Settings or in
first-run setup) to a name another file already carries is refused with the
file named, the same rule creating a company has always applied.
The Linux gate then found that `docker compose up` had been broken since
v2.8.0: no migration ever created the `users` table (the app made it at
startup), and the v2.8.0 preferences migration referenced it, which SQLite
tolerates and PostgreSQL refuses. A migration now creates `users` ahead of
that reference, a test walks the migrated schema for any foreign key whose
target no migration creates, and under PostgreSQL the company list flags
the database the server is connected to as current so an agent can tell
which books it reached.
Behind that lay an older one: the production guards that demand a TLS
database connection and an HTTPS redirect refused the compose stack's own
plaintext bridge-network URL, so the documented one-command install had not
started since those guards landed in v2.1. The compose file now declares
`SLOWBOOKS_PRIVATE_NETWORK=1`, which relaxes exactly those two transport
checks with a logged warning and nothing else; the encryption-key guards are
never relaxed, and the install guide says what to change before exposing
the stack beyond the host.
And a third, once the stack ran: with two uvicorn workers, both raced to
create the tables the migrations do not cover, one lost on a Postgres enum
type, and the container crashed and restarted on every first boot. Table
creation now takes a Postgres advisory lock so the second worker waits.

### v2.8.0 — Benefits, all-state payroll, and an overview you can arrange

### Export parity with import (#70)

**What comes in from QuickBooks can go back out.** IIF export now writes
everything the importer reads: the `!CLASS` list (names verbatim, archived
as HIDDEN=Y), a `CLASS` column on every transaction block so a tag never
falls off on the way out, jobs as `Customer:Job` rows, and three block
types that were import-only since they were added — **bills**, **deposits**
and **sales receipts** (`CASH SALE`). A full export re-imports into the same
books with no errors and no duplicates. CSV export gained bills, deposits,
sales receipts, classes and jobs, with class, job and cost code on every
line. The IIF and Import/Export pages carry buttons for all of it.

### Accessibility

**Striving toward WCAG 2.1 AA.** The audit's six app findings are fixed:
every table header declares its scope, icon-only remove and close buttons
carry labels, toast notifications announce through a live region, modals
are real dialogs (focus moves in, Tab stays inside, Escape closes, focus
returns to what opened them), the reconciliation difference says
"Balanced" or "Out of balance" in words rather than colour alone, and the
muted text colour now clears the AA contrast ratio in both themes. The
bigger gap was PDFs: every PDF the app produces — invoices, statements,
pay stubs, W-2s, 1099s, 940/941, reports — is now **tagged (PDF/UA-1)** with
a declared language and title, so a screen reader gets headings, tables
and reading order instead of a picture of text. See
[docs/accessibility.md](docs/accessibility.md) for the statement and the
contact path; this is a commitment, not a compliance claim.

### Sales tax per line

**A labor line and a taxed part can share one invoice.** The invoice's tax
rate used to apply to the whole subtotal, even though items already carried
a taxable flag. Now every line on an invoice, estimate, sales receipt and
recurring invoice has a **Tax** checkbox: it starts from the item's flag
(and turns off for every line when the customer is marked non-taxable), you
can flip it per line, the totals only tax the checked lines, the flag rides
from an estimate into the invoice it becomes and from a recurring template
onto every invoice it generates, the Sales Tax report's taxable base counts
only taxed lines, and the PDF marks non-taxable lines when the document
carries tax. Field report from an IT shop that repairs customer-owned
devices (untaxed labor) and sells the part with install (taxed) on the
same invoice.

### Customizable overview

**The Company Snapshot is yours to arrange.** A **Customize** button on the
overview lets you hide any card, move cards up or down, and add cards from
a catalog; **Save layout** remembers it for your login (each user on a
Server Edition company gets their own; the single-password operator gets
one shared layout), and **Reset** brings back the standard overview. The
classic cards are all there — receivables, overdue invoices, active
customers, payables, bank balances, A/R aging, monthly revenue, recent
invoices and payments — and five new ones join the catalog:

- **P&L: This Month vs Last** — income, expenses and net side by side.
- **Cash Position** — cash on hand plus a 30-day forecast from receivables
  and payables coming due (assumes customers pay on the due date).
- **Open Purchase Orders** — committed but not yet billed, with the job.
- **Receipts to Review** — scanned receipts waiting to become a bill or
  expense, and how long before they expire.
- **Jobs: Budget vs Actual** — active jobs ranked by projected variance,
  each a click from its job page.

Every card loads independently, so one card with a problem shows its
error in place instead of taking the page down. The overdue-invoices card
now names who owes what and by how many days.

### Benefits engine

**A benefit is a code with a rule.** Payroll evaluates whatever codes are
attached to an employee: kind (deduction, benefit, both), calculation
method, which wage bases the pre-tax side reduces, an explicit sequence
(pre-tax codes apply in order and each changes the taxable base for the
next), and three separate limits — per period, annual, and a wage-base
ceiling. Rates are effective-dated and resolve against the pay-period end
date; processed runs snapshot the rules they used so a later change never
rewrites history. The employer side has its own rate and method including
tiered 401(k) matching, an expense and liability account per code, and a
remittance vendor — the Remittance tab totals what is owed and creates the
vendor bill. Employee groups are templates; an enrollment overrides them.
Loan-style codes carry a balance and stop at zero. PTO banks now carry
dollars and can post the accrued liability. The Deductions page became
Benefits; garnishments have their own page. Existing deduction types and
elections migrate onto codes and enrollments.

### Actual labor burden on jobs

Set the Labor cost type's burden method to **payroll** and the pay run
distributes real employer taxes plus job-routed benefit codes across the
jobs each employee's time entries hit, by hours, P&L-neutral. Time entries
then post base labor only. Replaces the flat percent from v2.7.0.

### State withholding for all 50 states and DC

Every state resolves to a payroll engine (Washington, California, New York
and Oregon keep their dedicated ones). The figures are the 2026 published
values with the source named per state in `docs/state-withholding.md`.
Employees gain the state W-4 inputs: allowances, extra state withholding,
an elected rate (Arizona), and a flat local rate for county and city taxes.
Verify against your state before filing; the table is re-checked every
January.

### Employee portal link

On the desktop the link now opens in the employee's browser instead of
inside SlowBooks, and Copy Link / Email to Employee give a full address.
The Details view says where that address is reachable from.

### Small things

- `GET /api/sales-receipts` lists receipts for API clients.
- The Company Snapshot is titled with your company name, which also sits
  in the toolbar and the window title.
- The splash shows what's new in the version you're running.

### Benefits engine — from the first macOS lap

- A post-tax deduction larger than the check used to leave a negative net
  pay on the stub and an unbalanced payroll entry on processing. Post-tax
  codes now take what is left after taxes and garnishments, in sequence,
  with the shortfall noted on the stub; net pay never goes below zero.
- The remittance report and bill follow a code's current vendor when the
  run was processed before the vendor was assigned.

### v2.7.0 — Jobs, job costing, and receipt intake

The two most-requested features since Server Edition, each field-tested on
Windows (SkyTech / VonHolten308) and macOS (Keith's laps on #73 and #86).
#### Jobs — QuickBooks-style Customer:Job / Projects (milestone 1)

**Every posted line can now carry a job (and a class).** A job is a
customer's project — "Smith: Kitchen Remodel" — and the unit of job
costing. Invoices, bills, expenses, card charges, journal entries, sales
receipts and estimates take a Job on the header; invoice, bill and journal
lines can set their own job and class, and a line without one inherits the
header's. The ledger line is the source of truth, so the new **Jobs** page
(Customers & Sales) and the **Job Profitability** report show income,
costs, net and margin per job straight from posted activity — the "No job"
row holds everything untagged, so the report's totals equal the Profit &
Loss for the same period, the same reconciliation promise P&L by Class
makes. Job detail lists every posted line attributed to it (the job cost
detail). The Customer Center lists a customer's jobs and can create one.

Jobs carry what a contractor tracks: status (pending, awarded, in progress,
closed, not awarded), job number, type, dates, site address and contract
amount, so the detail can show billed-vs-contract. A job with posted
activity is never deleted — mark it inactive and it leaves the pickers.

**The cost model: drill-down, every kind of cost, burden, budgets and
variance (milestone 3).** Feedback from the first lap was that jobs
existed but there was no way to drill down or to get the extra and
edge-case costs onto them. Now:

- **Cost codes nest** (division › code › sub-code, any depth) with roll-ups
  at every level, your own numbering, and a CSV import
  (`code,name,cost_type,parent_code`). **Cost types are yours to edit** —
  add permits, bonding, warranty, split labor — each with a burden % and
  the accounts it posts through.
- **Job Cost Entry**, a new document for costs that aren't a bill:
  internal labor at an employee's loaded rate, owned-equipment hours from
  an Equipment list, mileage, small tools, burden, corrections. It debits
  job cost (tagged to job, code and type) and credits an offset account
  (applied labor, applied equipment, applied overhead — all contra-expense
  accounts on the P&L) — the applied-cost pattern, so the company P&L is
  unchanged while every job carries its share. Settings → Cost Types →
  **Create default offset accounts** sets all of that up in one click,
  pointing each cost type at the chart's own COGS account (Materials,
  Labor, Subcontractor) so the P&L keeps its cost categories. **Allocate a Cost** spreads one amount
  across jobs by labor hours, revenue, costs, equally, or by weights.
- **Time entries post to jobs.** Employees get a job cost rate and a burden
  %; approved time tagged to a job posts as labor cost at that rate
  (overtime at 1.5×, double-time at 2×) with the burden as its own line,
  one click from the time list or the job's Time tab.
- **Budgets and variance.** Each job carries a budget per cost code (or
  per type, or whole-job), seeded from an estimate — estimate lines gained
  a cost code and a unit cost, so cost = qty × unit cost and revenue = the
  line amount — or typed in. The job page shows, at every level, the
  columns contractors read weekly: Original, Changes, Budget, Committed,
  Actual, Projected (actual + committed), Variance (budget − projected),
  % Used, and estimated vs actual revenue.
- **The job page** replaces the modal: Overview (headline figures and a
  by-type table), Cost Detail (the expandable tree — type › division ›
  code › sub-code › posted lines, each line opening its bill, invoice,
  expense, journal entry or job cost), Budget, Transactions and Time tabs,
  with a period filter and a job-to-date default. A **Job Budget vs
  Actual** report lists every job's headline figures.
- Also fixed on the way: the Time Entry form was sending hours under the
  wrong field names, so every entry saved with zero hours.
- From the first macOS lap: the labor offset was a balance-sheet account,
  so labor landed on the P&L twice once payroll ran — it is a P&L contra
  now, like the other offsets. Rejecting a time entry that was already
  posted to a job voids that job cost. Re-seeding a budget from an
  estimate leaves hand-edited rows alone, and an estimate line with no
  unit cost budgets zero cost (unknown) rather than the sale price.

**Cost codes, billable costs and committed cost (milestone 2).** Settings
gained a **Cost Codes** chart — which part of a job a cost belongs to ("03
Concrete", "26 Electrical"), each with a cost type (labor, material,
subcontract, equipment, other) and an optional default account — with a
one-click load of the CSI MasterFormat divisions. Bill lines, journal
lines, purchase-order lines and expenses take a cost code, and bill lines
and expenses can be marked **billable** to the job's customer (the
unbilled-costs-to-invoice step arrives with progress billing). The job
detail rolls costs up by code and type, and shows **committed cost**: the
value of sent, partially received and received purchase orders tagged to
the job that has not yet become a bill. Purchase orders take a Job on the
header (and per line); converting one to a bill carries job and cost code
onto every bill line.

**QuickBooks migration keeps the hierarchy.** IIF imports split
`Customer:Job` names into the customer and a job under it (customer list
rows and every invoice, sales receipt and estimate); QBO imports turn
sub-customers ("Projects") into jobs under their parent. A flat customer
that already carries the colon from an earlier import keeps matching, so
re-imports are stable.

The estimate form also gained the Class field that was computed but never
rendered. Design and the rest of the plan (cost codes, committed cost,
change orders, progress billing, time and burden, WIP):
[docs/design/projects.md](docs/design/projects.md).

#### Receipt intake — scan a receipt into the Sales Receipt / Bill form

A new **Scan Receipt** button on both the Enter Sales Receipt and Enter
Bill forms uploads a receipt image or PDF, runs it through local OCR
(Tesseract), and pre-fills the form: date, merchant/vendor hint, and the
grand total as a single line (Qty 1 × Rate = total), with detected tax
split out on the Sales Receipt form (tax rate field) and noted in Bill
Notes (bills have no tax field). The operator always reviews before
saving, and the source image/PDF attaches to the saved document so every
scanned entry keeps its evidence.

Per the design notes, this is **zero new Python dependencies** —
tesseract and poppler-utils are called directly via subprocess and stay
the user's install (never bundled into the signed installers); the
Docker image installs both system packages. When the binary is absent,
the feature degrades gracefully: the button is disabled and the Settings
page shows "install Tesseract to enable scanning." Parsing is
deterministic (regex/anchor extraction for date, total, tax, merchant) —
no AI, no bundled models. Design + API contract:
[docs/design/receipt-intake-spec.md](docs/design/receipt-intake-spec.md).

**Expenses — the form most receipts actually belong on.** A receipt for
something already paid (card, cash, check) is neither a bill (money
still owed) nor a sales receipt (money taken in); entering one used to
mean a bill plus a payment, or a journal entry. The new **Expenses**
page (Vendors & Payables) records it in one step — vendor, expense
account, the bank or credit-card account it was paid from, amount — as
a single balanced posting (DR expense, CR paid-from), with the Scan
Receipt button, box-to-fix canvas, and attachment on save, exactly like
bills. Paid From lists bank/cash assets and credit-card liabilities,
defaulting to Checking.

**Vendor quick-add on the Bill and Expense forms.** A scanned merchant
the books don't know yet no longer dead-ends the form: the vendor
picker gained "+ New Vendor" with an inline name box; a scan that
doesn't match an existing vendor pre-fills it, and the vendor is
created on save (a near-duplicate name resolves to the existing
record instead of a twin).

**Box-to-fix canvas hardening**, from the first hands-on hardware lap:
a box dragged over two figures (tax + tip) is refused with the numbers
it saw rather than silently taking the first; any refused read — no
value, two values, or a value the form won't accept (a "tax" larger
than the subtotal) — leaves no box on the scan and no stale value on
the field buttons, so the next drag starts clean. Field buttons moved
below the canvas, a drag paints immediately, and a box recolors the
moment it's labeled instead of after the read comes back.

**Highlights land on the right words.** The colored boxes the scan
draws over the image are placed by matching the parsed values back to
the recognized words; a receipt that prints the same figure twice (a
line-item price and the grand total, or "CASH" repeating the total)
used to get the box on the first hit, and the Date box went to the
first thing with a slash or dash in it (an invoice number). The boxes
now go to the word on the labeled line — lowest one for totals — and
to the word that actually prints the parsed date in whatever order the
receipt used. The values on the form were already right; only the
highlight moved.

**Merchant template memory** no longer anchors a remembered box on a
word that repeats on the page when a unique label is on the same line
("Inclusive" over "GST"), records which occurrence it meant when every
label repeats, and fails closed — canvas takes over — when a rescan
doesn't repeat the anchor the same way. A remembered amount or date box
that reads only a bare digit run on a new print (a template that landed
on a tax-ID number) is discarded instead of filling the form with it.

**Windows: the second scan of a session no longer crashes the app.** On
Windows the built-in text recognizer was driven from a throwaway thread
per scan; when that thread exited, Windows tore down the component
runtime the recognizer had been created in, and the next scan jumped
through a stale handle — the server process died and the window
reported "SlowBooks isn't responding (network error)" right after the
first bill or expense was saved from a receipt. All recognizer work now
runs on one thread that lives as long as the app does.

**The merchant name gets a highlight box too.** The scan now boxes the
run of words on the image that spells the parsed merchant name (pink),
alongside the totals and date, so it can be corrected by tapping like
the others; a name recalled from a remembered layout that isn't printed
on the page draws nothing.

**Bill numbers come off the receipt, and never block the entry.** The
Bill # is the vendor's own invoice number — that is what stops the same
invoice being entered twice (the check is per vendor, so two vendors
can both send invoice 111). The scan now reads it from the receipt
("Invoice No", "Receipt #", "Check", "Trans No" …) into Bill # and the
expense Reference; a receipt that prints none can be saved with the
field blank and gets `<date>-<vendor initials>` (suffixed if that vendor
already has one that day).

**Expenses can be voided.** A recorded expense booked to the wrong
account (checking instead of the credit card) now has a Void button on
the list and in its detail; like bills and journal entries it posts the
mirror-image reversing entry, keeps the original in the ledger, respects
the closing date, and shows the row as void. Enter it again to correct.

**Scan Receipt field buttons are readable in dark mode.** The Total /
Tax / Subtotal / Date / Merchant buttons under the receipt used pale
fills with dark text regardless of theme — near-invisible on the dark
theme. Dark mode now uses deep opaque fills with light text (8–10:1
contrast); light mode keeps the pale fills with darker text.

**Invoice / Ref # has its own box on the scan.** The picker under the
receipt gained an **Invoice / Ref #** button (teal): draw it around the
vendor's document number and it lands in Bill Number (bills) or
Reference (expenses); the auto-parse also outlines the number it found,
and a taught box is remembered per merchant like the others. The
auto-parse no longer skips an invoice line because a "Pax"/"Table"/"Tel"
word sits after the number on the same line.

**Day-first dates parse.** `14-02-2018`, `14/02/2018`, `14.02.18` — any
numeric date whose US reading is impossible — now resolves day-first
(US ordering still wins when both readings are valid, so `12/02/17` is
December 2), and month-name dates accept a two-digit year or dashes
(`28 Mar 18`, `05-JAN-2017`). A date box that reads something the parser cannot turn into
a date no longer reports "applied to the form" while the date input
stays empty; it says what it read and asks for a redraw or a manual
entry.

**US register tape parses (Walmart, Whole Foods, Costco phone photos).**
`TAX 1 7.000 %` is a tax *rate* line, not a 7.00 tax — a third decimal
or a trailing % never reads as money. A return-policy or promotion line
("purchases made on or after 9/15/2020") can no longer supply the
transaction date. Walmart's `TC#` is the receipt number; the `REF #`
printed beside APPR CODE / NETWORK ID / TERMINAL # is the card
authorization and is ignored. The Invoice / Ref # button is present on
the picker under the receipt (build 47 drew the box but had no button
to assign it to).

**Tilted photos read the right rows.** On a phone photo taken a couple of
degrees off square, the amounts down the right edge of a 2000-pixel
receipt sit a full line below the labels they belong to, and the row
builder for the native engines put them on the neighbouring row — total
survived but subtotal and tax silently took the wrong values (found on
the macOS hardware pass). The engines now report each line's tilt (Apple
Vision from its corner points, Windows OCR from its line grouping) and
the rows are straightened before they are read; verified to 8 degrees.
Also from that pass: the Settings OCR row names the built-in engine
instead of assuming Tesseract everywhere, Apple Vision lists its
recognition languages, and the macOS build's smoke test now proves Vision
survived freezing.

**Desktop launcher:** `--data-dir` (Server Edition scheduled task,
headless test rigs) now relocates the per-user `.env` along with the
data directory; it used to write `DATABASE_URL` into the launching
user's own `%LOCALAPPDATA%` `.env`.

### v2.6.3 — Classes cross over, and report CSVs read ANSI

**Classes now come across from QuickBooks.** A class list export
(File > Utilities > Export > Lists > Class List) previously vanished on
import: the IIF parser only recognized accounts, customers, vendors and
items, so the `!CLASS` section fell through the skip-unknown-sections
path. A transaction IIF never carries the definitions either — CLASS
appears only as a column on split lines — which left no way into the
class list but typing every name into Settings → Classes by hand, and
every transaction citing one failed its document. The list imports now,
ahead of anything that can cite a class, so a single file holding both
the list and the transactions lands in one pass. QuickBooks'
"Parent:Child" subclass paths are kept verbatim (the split lines use
that same path, so this is exactly what makes the two match), inactive
classes arrive archived, and re-importing a list is a no-op. An unknown
class on a transaction still stops that document rather than being
invented — the error now names the list export as the fix. (#69)

**Report-CSV import follow-ups**, from the #62 post-merge review: block
types the Check and Deposit Detail parsers don't handle are now counted
and warned about ("3 'Bill Pmt -Check' block(s) skipped") instead of
being silently dropped, so a full Check Detail export no longer looks
like it imported cleanly when it didn't. CSV uploads also fall back to
Windows-1252 when UTF-8 fails — QuickBooks Desktop's Save-as-CSV
frequently writes ANSI, and a payee like "José" used to 500 the upload.
All four CSV import endpoints got the fix; a file neither encoding can
read returns a guided error. (#67)

### v2.6.2 — Report-CSV imports & field fixes

**Field fixes** (both from a Server Edition user's report, #64/#65):

- Creating a customer or vendor with a blank Email box failed with an
  unexplained "unprocessable entity" — blank email now means "no
  email", and validation errors name the field they're about.
  (Workaround before this release was entering any valid email.)
- The Server Edition install script now copies existing desktop books
  (company files, encryption key, uploads, backups) into the server's
  data home, as the docs always claimed; a wrong run location stops
  with a guided message; and — found reproducing the report on real
  hardware — the startup task could never be registered from the
  normal installed path at all (PowerShell 5.1 mangled the quoting on
  the spaced "Program Files" path and the script printed success over
  the failure). Task creation is fixed and failures now stop the
  script loudly. Field-verified end-to-end on hardware.

### Deposits and checks from QuickBooks report CSVs

The report-CSV path now covers three exports, auto-detected by their
columns on one upload: **Deposit Detail** (each deposit becomes the
journal entry moving its payments from Undeposited Funds to the bank),
**Check Detail** (bank credit + expense debits — including payroll
checks, whose withholding lines credit their liability accounts and
net to the check amount; sign-aware parsing again, proven against a
real customer's export), and the Transaction Detail sales-receipt
report below. Blocks that don't balance or reference missing accounts
error individually with a pointer to import the chart of accounts
first; re-uploads dedup.

### Sales receipts from a QuickBooks report CSV

QuickBooks Desktop can't export transactions to IIF, so the sales-
receipt migration doc pointed Desktop users at a Transaction Detail
report export — which previously had nowhere to land. It does now:
**QuickBooks Interop → Sales Receipts from Report CSV** imports a
"Transaction Detail by Date" export (filtered to Sales Receipt), each
receipt becoming a paid sale + payment with balanced journals.

Shaped by a real customer's export, so the parser handles what real
files contain: applied-deposit contra lines that reduce the total
(sign-aware — an absolute-value parse would inflate them), percentage
tax rows carrying the tax agency's name, deposits-only receipts,
thousands separators, and per-receipt balance checks with clear
errors. Unmatched account names post to default income with a warning;
re-uploads dedup by customer + date + total. Receipt numbers keep the
report's Num where free (SR-prefixed on collision).

### v2.6.1 — The receipt now looks like a receipt

- The printed/saved sales receipt was the unmodified invoice template —
  titled INVOICE, with Due Date, Terms, and Balance Due rows, saved as
  `Invoice_<n>.pdf`. It now renders as a SALES RECEIPT: date only, Sold
  To, Total + Paid (no balance line — nothing is due), filename
  `SalesReceipt_<n>.pdf`, and the same for the email attachment name.
  Found on macOS hardware by the build maintainer during the v2.6.0
  release pass. (#60)
- The PDF's Bill To / Sold To block always prints the customer's name
  now: the template fell back on a `customer_name` attribute only some
  callers stamped onto the invoice, so the direct PDF route printed a
  bare header whenever the customer had no address on file.
- `SHA256SUMS.macos` now also lists the stable-named
  `SlowBooksPro-macos-arm64.dmg`, so the README's direct download can be
  checksum-verified, not just the versioned asset.

### v2.6.0 — Sales receipts: one-screen POS sales + QuickBooks import

For businesses that ring up sales at a counter instead of invoicing:
a QuickBooks sales receipt is an invoice paid at the moment of sale,
and SlowBooks now models it exactly that way — an Invoice flagged
`is_sales_receipt` plus a Payment for the full total, so every
existing report, PDF, export, and void path works unchanged. Schema
migration `c7d8e9f0a1b2` adds the flag (drop-in; new databases need
nothing).

- **Enter Sales Receipts screen** — new sidebar page with a
  one-screen form: customer (with quick-add), payment method,
  check #/reference, deposit-to account (defaults to Undeposited
  Funds), tax, class, currency, and line items. `POST
  /api/sales-receipts` composes the existing invoice and payment
  routes, so numbering, closing-date enforcement, FX, and
  inventory/COGS behave identically to documents entered separately;
  if the payment half fails the invoice half is voided rather than
  left as a stray open balance. Receipts list on their own page and
  no longer clutter the Invoices list (`GET
  /api/invoices?is_sales_receipt=...` filters either way; omitting
  the param returns everything, as before).
- **IIF import: `CASH SALE` blocks** — QuickBooks Desktop's sales
  receipts previously fell into the silently-skipped bucket. They now
  import as paid invoice + payment with balanced journals (deposit
  account from the TRNS header, Undeposited Funds fallback).
  Counter sales with a blank Customer:Job land on an auto-created
  "Walk-In Customer" (reported as a warning); unnumbered receipts get
  the next invoice number, and re-imports dedup by document number or
  customer + date + total.
- **QBO import: SalesReceipt entity** — the QuickBooks Online
  importer pulls sales receipts alongside invoices and payments, with
  the same id-mapping dedup; the QBO page gets a Sales Receipts
  import checkbox (import-only — there is no matching export entity).
- **docs/migrate-from-quickbooks.md** — new guide covering both
  paths, including the fact that Desktop's built-in IIF export is
  lists-only and the clean Transaction Detail report recipe for
  getting sales history out.

### v2.5.3 — API hardening, from a full-surface sweep

Every one of the API's 357 operations was driven end-to-end on Windows
(installer) and Linux (source, PostgreSQL 17); everything that surfaced is
fixed here. No schema migrations; drop-in upgrade from 2.5.x.

**Data-integrity fixes**

- An invalid `pay_type` or `role` on an employee was written as-is and then
  made the row permanently unreadable — one bad `PUT` returned 500 for the
  record *and* for `GET /api/employees` company-wide, with no API-level
  recovery. Both fields are now validated as enums (422 at the edge), the
  same treatment `pay_frequency` and `filing_status` already had. For rows
  corrupted before the fix, `scripts/repair_employee_enums.py` repairs in
  raw SQL (dry-run by default; `--apply` to write).
- The migration dry-run tolerated a one-cent journal imbalance the importer
  then refused, so `ok=true` could precede a mid-import 500. The gate now
  applies the importer's exact-balance rule, including to synthesized
  opening-balance journals.
- Customer and vendor names: blank/whitespace-only names rejected, lengths
  capped to the column width (was: opaque 500 on PostgreSQL, silent
  overflow on SQLite), obviously malformed emails rejected. The CSV and
  IIF importers honor the same rules — an IIF transaction with a blank
  NAME no longer auto-creates an unnamed customer.

**Correctness / API behavior**

- Emailing an invoice (and Settings → "send test email") called
  `send_email()` with a stale signature and could never succeed; both now
  work, report 502 with a pointer to the email log when SMTP fails, and no
  longer double-log.
- Account endpoints return 409 with a real message instead of leaking
  database errors as 500s (delete-with-history, duplicate account number);
  an account can no longer be made its own parent.
- `/openapi.json` no longer requires auth, so the documented agent flow
  ("discover from the spec") works; the spec now declares its bearer
  security scheme, with genuinely public routes exempted.
- API tokens can no longer clear or roll back the closing date, nor set
  the closing-date override password; moving the date forward (tightening)
  is still allowed, and signed-in users are unaffected.
- Machine-originated audit rows (e.g. the token `last_used_at` stamp) are
  attributed to an explicit `system` principal instead of NULL.
- `SlowBooksPro.exe --help` with piped/redirected output hung the frozen
  Windows build forever on an invisible error dialog (UnicodeEncodeError
  under cp1252 inside argparse). Launcher stdio is now total; verified on
  Windows before/after.

**Docs**

- INSTALL.md's native Linux path works as written on PEP 668 distros
  (venv steps, `.env` honored by alembic, APP_DEBUG guidance);
  `.env.example` no longer recommends a FORCE_HTTPS setting the app
  refuses to boot with; README operation count corrected.

**Report display fix**

- Balance-sheet and P&L lines rendered in the app wrapped every amount in
  an absolute value, so a contra-balance account displayed positive while
  the totals summed real signed values — visibly "$100 + $400 + $600 =
  $300" after an unapplied customer payment drove A/R negative (a
  legitimate prepayment). Lines now render signed, matching the totals
  and the PDF output, which were always correct. (#56)

**macOS releases now sign themselves in CI**

- Tag builds sign, notarize, and staple the macOS DMG on the runner using
  the same release tooling the maintainer ran locally, and attach it to
  the release alongside the Windows assets. Starting with this release the
  macOS publisher identity is **Trenton Von Holten** (previously releases
  were signed by the macOS maintainer's own Developer ID).

20 new regression tests (1162 total).

### Native macOS desktop

- Added a signed and Apple-notarized native app for Apple Silicon Macs running
  macOS 14 or newer, distributed as a drag-to-Applications DMG.
- Desktop companies, settings keys, uploads, logs, and backups persist under
  the user's Application Support directory; upgrades never place writable data
  inside the app bundle.
- Bundled PDF libraries and the Cocoa window backend are exercised before a
  build can become a release candidate.

### v2.3.0 — Migration onramps

**Migrate Data** — one page that brings accounting history in from six
systems, each behind the same dry-run-gated engine (nothing is written
until every reconstructed journal balances and, when supplied, the
trial balance reconciles):

- **MYOB** — fully validated against MYOB's own Clearwater sample
  company (101 accounts, 328 journals, ledger balanced to the cent,
  every account reconciling exactly to MYOB's trial balance). Handles
  tab-separated classic exports, dd/mm/yyyy dates, header accounts,
  reused journal IDs, number-only GL rows, duplicate account names,
  and per-type journal file bundles. docs/migrate-from-myob.md walks
  the export flow.
- **GnuCash** — fully validated against real 5.5 exports (multi-split
  transactions, GUID grouping, signed per-split amounts, placeholder
  accounts).
- **Xero** — refactored onto the shared engine (behavior-identical).
- **Zoho Books** — chart validated against a live account's export.
- **Wave** — trial-balance report shape validated against a live
  account's export; supports both debit/credit and signed
  single-amount transaction exports.
- **Sage 50** — account-ID resolution, mm/dd dates, Sage's descriptive
  account types.
- Opening balances: trial-balance residuals that net to zero (the
  source system's account-setup balances, absent from any journal
  export) are detected and imported as one balanced opening journal.

**Dependencies** — refreshed across the board for the release
(FastAPI 0.141, Stripe SDK 15, cryptography 50, argon2-cffi 25,
python-multipart 0.0.32, psycopg2-binary 2.9.12); pip-audit clean.
The route-table introspection tests were taught FastAPI 0.141's new
nested-router shape, with a tripwire so a future shape change can
never silently empty the auth-contract suite again.

### v2.2.0 — The fork-integration release

The largest single release since 2.0: work mined from four community
forks (with per-commit attribution), two new payment processors, and
five major accounting features.

**Online payments — Stripe, PayPal, Square**
- Payment-provider abstraction with one shared, idempotent recorder
  (row-locked; a webhook and a status poll can never double-record).
- PayPal (Checkout Orders v2) and Square (Payment Links) join Stripe;
  enable any combination and the pay page shows a button per processor.
- Desktop installs record payments without webhooks: verified capture
  on the customer's return + a "Check Payment Status" button.
- Fixed: the public Pay button 401'd (checkout route was never
  session-exempt) and the success banner trusted a URL query param —
  it now renders only after provider-verified capture.
- Fixed (found in live sandbox testing): Square leaves paid
  payment-link orders in state OPEN; polling now recognizes them.

**Class tracking**
- QuickBooks-style class dimension on invoices, bills, estimates,
  credit memos, recurring, journals, deposits, and cc charges;
  managed in Settings; immutable "Uncategorized" system default.
- P&L by Class report whose totals reconcile exactly with the plain
  P&L; IIF SPL.CLASS resolves on import.

**Multi-currency**
- Foreign-currency invoices and bills booked at per-document rates
  (Bank of Canada feed prefill, always overridable); the ledger stays
  single-currency so every report and invariant holds exactly.
- Realized FX gain/loss posts automatically on BOTH sides: customer
  payments (A/R) and bill payments (A/P).
- Cross-currency allocations rejected with clear errors; online
  checkout guarded to home-currency invoices.

**Fixed assets**
- Register with per-type account mappings, straight-line and
  declining-balance depreciation runs (one journal per asset, salvage
  floor, idempotent re-runs), disposal with gain/loss, CSV import,
  and a reconciliation report.

**Migration onramps**
- Xero CSV import (chart + general ledger + trial balance) gated by a
  dry-run that verifies every journal balances and cross-checks the
  trial balance before anything is written.
- Opening Balances wizard: guided setup, normal-side posting rules,
  optional auto-balance to equity.

**Banking & interop**
- Bank CSV import for Chase checking/credit and PayPal exports,
  auto-detected by header signature, with content-derived dedup that
  survives re-imports without dropping legitimate same-day duplicates.
- IIF BILL and DEPOSIT transaction blocks (previously silently
  discarded), with strict vendor/account matching and
  duplicates-skipped reporting.

**Reports**
- Printable P&L and Balance Sheet PDFs plus the one-click Financial
  Statements Pack (P&L + Balance Sheet + Trial Balance, page-numbered),
  US Letter or A4 via a new setting.

**Hardening**
- Auth-contract regression suite: every API route proven to 401
  unauthenticated or match a justified-public pattern (295 combos).
- Upload size caps on all import endpoints; CREATE DATABASE identifier
  quoting; decompilation debug strings scrubbed from the DOM with a
  regression scan; version-stable ruff lint gate.

**Community**
Work in this release originates from the forks of Alex Jordan
(@LayoverLogic), Joel Macklow (@joelmacklow), @moshgrossman, and
@amazon1148 — authorship preserved per commit. Thank you.

### v2.1.1 — Windows field fixes (first-machine feedback)

- **Session cookie now reaches every native window and download.**
  pywebview's default `private_mode=True` partitions WebView2 cookie
  storage, so the print-preview/PDF window opened as
  `{"detail":"Not authenticated"}` and CSV/backup downloads failed with
  "Needs authorization" (saving the 401 JSON body as `.json`). The
  desktop shell now uses a persistent shared profile under
  `%LOCALAPPDATA%\SlowBooksPro\data\webview` — PDFs, exports, and
  attachment downloads work, and logins survive app restarts.
- **The installer now installs the WebView2 runtime when missing**
  (silent Evergreen bootstrapper, skipped if already present) instead
  of showing a "runtime is not installed" error on first launch —
  Windows 10 machines without Edge updates hit this.

### Native Windows desktop install (no Docker, no WSL2)

Replaces the WSL2/Docker-Engine Windows setup from PR #1 with a fully
native install: the app runs as a normal Windows process against SQLite,
in its own desktop window (pywebview → WebView2). Desktop-mode groundwork
contributed in PR #14; delivery is a signed Windows installer (see below).

- **Multi-company, QuickBooks-style:** each company is its own SQLite file
  under `%LOCALAPPDATA%\SlowBooksPro\data\companies\`, tracked in a
  `companies.json` manifest. A company picker appears at every launch;
  switching companies = close and reopen. Creating a company runs the real
  `alembic upgrade head` plus the Chart of Accounts seed against a fresh
  file. Company identity/settings already live per-database, so each file
  is fully self-contained.
- **Backups on SQLite:** `backup_service` gains a SQLite branch — backup/
  restore are consistent `.db` snapshots via sqlite3's online backup API.
  Postgres installs keep pg_dump/pg_restore unchanged.
- **Migrations now genuinely run on SQLite:** four ALTER-added FK
  constraints converted to Alembic batch mode and literal `now()` server
  defaults replaced with the dialect-portable `CURRENT_TIMESTAMP`
  (identical semantics on PostgreSQL; these migrations have already run on
  existing Postgres installs and never re-run).
- **Launcher:** `desktop_launcher.py` — env prep with a generated
  `PAYROLL_ENCRYPTION_SECRET`, company picker, uvicorn on 127.0.0.1,
  native window; closing the window stops the server.
- **Delivery is a signed installer**, not setup scripts: the
  `.bat`/`.ps1` bootstrap flow contributed in PR #14 was replaced by
  `SlowBooksPro-Setup-x64.exe` — a PyInstaller bundle (Python and the
  PDF-rendering libraries included, nothing installed system-wide) built
  by CI and code-signed via Azure Trusted Signing, so Windows shows a
  verified publisher instead of a SmartScreen warning.
- The Docker/Postgres multi-company path (separate databases per company)
  is unchanged and still used when `DATABASE_URL` is Postgres.

### Post-merge review fixes (PR #12 follow-up)

A deep review pass after merging the payroll/HR contribution surfaced and
fixed twelve issues plus a round of structural cleanups (commits `af65843`,
`68eb844`).

**Schema / migrations:**

- Six `Employee` columns (`portal_token_last_used`, `portal_token_expires_at`,
  `everify_status`, `everify_submitted_at`, `everify_closed_at`,
  `everify_notes`) and four whole tables (`document_audits`, `login_attempts`,
  `reseller_permits`, `portal_accesses`) existed only in the models — no
  Alembic migration created them. Startup `create_all()` masked the missing
  tables but never ALTERs the existing `employees` table, so employee
  creation, portal access, and E-Verify updates crashed with
  `UndefinedColumn` on any alembic-migrated PostgreSQL.
  `migrations/versions/d0e1f2a3b4c5` adds the columns;
  `migrations/versions/bc3c3c5fd0a6` adds the tables (existence-guarded so it
  works on databases where `create_all` already made them). Verified with a
  full model-vs-schema diff against a scratch Postgres — zero gaps remain.

**Correctness:**

- `app/services/iif_export.py` — payment export filtered with
  `.filter(not Payment.is_voided)`, which Python evaluates to
  `.filter(False)` at query-build time (`WHERE false`), so payment IIF
  exports were always empty. Restored the column comparison.
- `app/routes/invoices.py` — late fees were being applied to DRAFT (unsent)
  invoices: drafts get a terms-derived `due_date` at creation, so they
  qualified as overdue. Filter scoped back to SENT/PARTIAL. Fee rounding
  switched from bare `.quantize()` (banker's rounding) to `_q`
  (ROUND_HALF_UP) to match the rest of the ledger.
- `app/routes/bills.py` — `void_bill` gained the payments-applied guard that
  `void_invoice` already had: voiding a paid bill reversed the full A/P while
  the bill payment's cash JE and allocations stayed on the books,
  double-counting the outflow.
- `app/services/nacha_export.py` — `_split_net_pay` silently dropped
  unallocated net pay when an employee had only PERCENT/FIXED accounts and no
  REMAINDER/FULL account, producing an ACH file that underpaid the employee
  with no error. Now raises `ValueError` (the route maps it to 400).
- `app/services/payroll_service.py` + `app/routes/payroll.py` — the
  $1M/37% supplemental-withholding tier could never fire:
  `supplemental_federal_tax()` implements it but the call site never passed
  `ytd_supplemental`. YTD bonus-run wages are now threaded through
  (`_ytd_supplemental` helper; flat and gross-up paths). Deduction/gross/net
  rounding in the pay-run route unified on `_q` — bare `.quantize(CENT)`
  rounded half-cents the opposite direction from the service.
- `app/static/js/employees.js` + `app/schemas/payroll.py` — the pay-frequency
  dropdown emitted `semimonthly` but the enum value is `semi_monthly`, so
  semi-monthly employees 500'd at flush. JS fixed; `pay_frequency` /
  `filing_status` now typed against the model enums so bad values 422 at the
  edge. Dropped the stale pre-2020 W-4 `allowances` field from the form.
- `app/routes/credit_memos.py` + `app/services/recurring_service.py` — the
  MAX+1 numbering race fix invoices got (retry on `IntegrityError` against
  the UNIQUE constraint) now also covers credit memos and the recurring
  batch. The recurring path retries under a SAVEPOINT so one collision can't
  abort the whole batch; a template that can't get a number is left for the
  next run.
- `app/services/accounting.py` — closing-date enforcement moved inside
  `create_journal_entry()` so every entry point inherits it. Recurring runs,
  IIF/QBO imports, and inventory hooks could previously post into closed
  periods that the UI forbids. Route-level checks kept for earlier, clearer
  errors; `bypass_closing_date` kwarg exists as an operator escape hatch but
  nothing sets it.
- `app/routes/portal.py` — the token-in-URL POST handlers (W-4 elections,
  direct-deposit accounts, PTO requests) resolved the employee without
  writing a `portal_accesses` audit row, while their cookie-based twins
  logged everything. All portal mutations are now audited.
- `app/routes/payroll.py` — the JSON tax-form endpoints (`/forms/w2|w3|940|941`)
  hand-rolled box math that diverged from the PDF path — W-2 box 3 returned
  raw gross with no Social Security wage-base cap. They now delegate to the
  same `compute_w2/w3/940/941` services the PDFs use; the 941 also now counts
  only PROCESSED stubs.

**Hardening / cleanup:**

- ABA check-digit validation (`validate_routing_number`, weights 3-7-1) for
  direct-deposit routing numbers — used by the portal and the employees API;
  previously both accepted any 9 digits, so a typo'd routing number wasn't
  caught until the bank bounced the ACH file.
- `_q`/`CENT` money rounding consolidated onto `app/services/accounting.py`
  (was copy-pasted across ~17 service modules; one divergent copy in
  `inventory_service.py` kept deliberately — it quantizes quantities/costs to
  4 dp).
- Portal token/cookie handler bodies deduped into shared `_save_profile` /
  `_add_bank` / `_request_pto` helpers; `_client_ip` moved to
  `app/services/request_utils.py` (was duplicated in `auth.py` and
  `portal.py`).
- N+1 query fixes: time-entries list + pay-period summary, PTO requests
  list, pay-run deduction loading, and W-2/W-3 generation (one stub fetch
  for the whole year, bucketed in memory, instead of 2+ queries per
  employee).

**Test coverage:**

- `tests/test_closing_date_enforcement.py` — four new service-layer tests
  including the recurring-service path.
- `tests/test_no_nplus1_in_list_endpoints.py` — extended to time-entries and
  PTO list endpoints.
- Routing-number fixtures updated to ABA-valid values (`021000021`).
- Full suite: 458 passed; black/ruff clean.

---

### AP void — `POST /api/bill-payments/{id}/void`

The customer-payment void (`POST /api/payments/{id}/void`) had no AP mirror.
Any voided customer receipt restored A/R cleanly; vendor bill payments could
not be undone at all. This gap is now closed.

**What was added:**

- `app/routes/bill_payments.py` — `void_bill_payment()` endpoint. Acquires a
  `with_for_update()` row-lock on the payment before checking `is_voided`,
  so two concurrent void requests cannot both pass the guard and post
  duplicate reversing JEs. Posts a reversing JE (swaps debit/credit on every
  original JE line). Walks each `BillPaymentAllocation` with a second
  `with_for_update()` lock and restores `amount_paid` / `balance_due` /
  `status` on each bill. Respects the closing-date guard — cannot post a
  reversing JE into a locked period.

- `app/models/bills.py` — `is_voided = Column(Boolean, …)` on `BillPayment`.

- `app/schemas/bills.py` — `is_voided: bool = False` on `BillPaymentResponse`.

- `migrations/versions/c9d0e1f2a3b4_add_is_voided_to_bill_payments.py` —
  Alembic migration adds the column with `server_default=false()`.

- `app/static/js/bills.js` — `BillsPage.voidBillPayment()` wires the new
  endpoint to the UI so the wiring audit passes.

**Test coverage:**

- `tests/test_void_reversal_symmetry.py::test_bill_payment_void_restores_bill_balance`
  — full void cycle: bill paid → void → balance restored, ledger balanced,
  double-void rejects 400.
- `tests/test_closing_date_enforcement.py::test_bill_payment_void_respects_closing_date`
  — reversing JE cannot land in a closed period.

---

### Whole-repo lint & format sweep

`black 24.8` and `ruff 0.6` run against `app/ tests/ scripts/` without an
allowlist — every file is now clean. CI replaced a 30-line per-file allowlist
with a two-line whole-tree gate.

Fixes applied to reach a clean tree:

- **E402** (imports not at top of file) in `app/routes/invoices.py`,
  `app/routes/stripe_payments.py`, `app/routes/reports.py`,
  `app/routes/saved_reports.py`, `app/services/iif_import.py`.
- **E741** (ambiguous `l` variable name) in `app/services/accounting.py`,
  `app/routes/journal.py`, `app/routes/reports.py`,
  `app/services/iif_import.py`, `app/services/tax_export.py`,
  `scripts/repair_rounding_drift.py`.
- **black reformatting** of ~40 files with over-long lines.

---

### Books-balance invariant tests (`test_books_balance_invariants.py`)

Seven cross-feature invariant tests that exercise the entire accounting layer
end-to-end through the API:

1. Every posted JE has `Σ debit == Σ credit`.
2. Full ledger `Σ debit == Σ credit` across all transactions.
3. Balance sheet balances: `A == L + E` (with synthetic Net Income line).
4. A/R aging total matches open invoice balances.
5. A/P aging total matches open bill balances.
6. Analytics A/R widget matches `/api/reports/ar-aging`.
7. P&L net income matches the balance-sheet synthetic equity line.

`_build_scenario()` creates a realistic dataset (3 invoices, 2 bills,
payments at various states) before each invariant check.

---

### Shell-injection AST audit (`test_subprocess_safety_audit.py`)

Four CI-gated static-analysis tests that verify the subprocess/shell call
surface is safe:

1. Zero `subprocess.*` calls in `app/` or `scripts/` use `shell=True`.
2. Zero `os.system` / `os.popen` / `commands.getoutput` in production code.
3. All three subprocess callsites use list-form args (not string
   interpolation).
4. Every bash script in `scripts/` double-quotes all `$VAR` expansions.

Uses `ast.NodeVisitor` for Python files; regex for shell scripts. Runs in
< 1 s. Result: zero vulnerabilities found in the codebase.

---

### Void-reversal symmetry tests (`test_void_reversal_symmetry.py`)

Six property-based invariant tests for void semantics:

1. Full payment void restores invoice balance and keeps ledger balanced.
2. Partial payment void restores only the voided portion.
3. Bill-payment void restores bill balance, keeps ledger balanced, double-void
   rejects 400.
4. Invoice void (no payments applied) → status VOID, balance\_due 0, ledger
   balanced.
5. Invoice void with payments applied rejects 400/409 (would double-reverse
   A/R).
6. Double-void of same payment rejects or is a no-op — never posts a second
   reversing JE.

---

### Closing-date exhaustive sweep (extended `test_closing_date_enforcement.py`)

Expanded from 3 to 13 tests. Added `test_bill_payment_void_respects_closing_date`
(the AP void guard), plus nine exhaustive sweep tests covering every
direct-create route that accepts a user-supplied date and posts a JE:
invoices, bills, payments, bill-payments, credit memos, journal entries,
CC charges, deposits, batch payments.

---

### IIF round-trip tests (`test_iif_round_trip.py`)

Three tests verifying the Intuit Interchange Format export/import pipeline:

1. Chart-of-accounts export → reimport preserves all accounts by number.
2. Customer names with metacharacters (`\t`, `\n`) are sanitized on export;
   the sanitized record can be reimported cleanly.
3. Invoice TRNS + SPL rows sum to zero (double-entry identity): the A/R debit
   plus income credits plus tax credit == 0.

---

### Production-readiness sweep (rounding / races / N+1 / closing-date / secrets)

A 19-commit program-wide audit of every JE-posting path and money
boundary in the codebase. All 452 tests pass; live walkthrough
exercised every flow listed below.

**Money math — rounding drift fixed at the source.**
The class of bugs: `qty * rate` was stored to `Numeric(12, 2)` columns
without being quantized first. SQL rounded each line on the way in,
so `sum(line.amount)` no longer equaled the stored `subtotal` after a
round-trip. Fix: every per-line money expression now goes through
`_q()` (ROUND_HALF_UP at 2 decimals) **before** being assigned. Applied
to invoices, bills, POs, estimates, credit memos, and the recurring
invoice generator. `compute_line_totals()` is the single canonical
helper. `scripts/repair_rounding_drift.py` detects and repairs
pre-fix rows (dry-run by default; `--apply` writes).

**Auto-number races — IntegrityError retry on every doc series.**
`SELECT MAX(num) + 1` followed by `INSERT` has no lock. Two concurrent
creates would both see the same MAX and collide on the UNIQUE
constraint. `create_invoice`, `create_po`, and `create_estimate` now
catch `IntegrityError`, roll back, and retry up to 10 times. Pinned
by `tests/test_invoice_number_race.py`.

**N+1 SELECT storm — eager-loaded six document list endpoints.**
`for inv in invoices: inv.customer.name` was firing one SELECT per
row. Added `joinedload(.customer)` + `selectinload(.lines)` to
invoices, bills, POs, estimates, payments, and credit memos. Also clamped
`skip`/`limit` on the paginated routes audited in that sweep
(1 ≤ limit ≤ 1000; skip ≥ 0). Pinned by
`tests/test_no_nplus1_in_list_endpoints.py`.

**Closing-date enforcement — plugged three bypass paths.**
A code audit found three routes that posted dated JEs without calling
`check_closing_date`:
- `POST /api/purchase-orders/{id}/convert-to-bill`
- `POST /api/estimates/{id}/convert`
- `POST /api/payroll/{id}/process`

Each one let an operator land a JE into a closed period by routing
through a "convert" or "process" verb instead of the direct create.
All three now call the guard. Pinned by
`tests/test_closing_date_enforcement.py`.

**Stripe webhook idempotency under contention.**
Stripe retries with backoff; two webhook deliveries can land
milliseconds apart. The check-then-insert against `Payment.reference`
let both pass the existence guard and create duplicate payments. Fix:
`with_for_update()` on the invoice row before the idempotency check,
so the second arrival serializes behind the first and sees the
already-recorded payment.

**Settings — secret redaction on GET.**
`GET /api/settings` was returning `stripe_secret_key`,
`smtp_password`, `closing_date_password`, and the QBO tokens in
plaintext. Fix: response runs through `_redact_secrets()`, which
replaces any non-empty secret with `"********"`. `PUT` treats the
placeholder as a no-op so a UI round-trip can't overwrite the real
value with `"********"`. Pinned by `tests/test_settings_redaction.py`.

**Input validation at the boundary.**
Schema-level rejection of impossible inputs: zero-line invoices /
bills / POs / estimates (422), negative quantity / rate / hours (422),
zero or negative payment amounts (400), payment allocations exceeding
invoice balance (400), duplicate `(vendor_id, bill_number)` pairs
(409). 17 tests in `tests/test_input_validation.py`.

**Payment void race.**
`void_payment` walked allocations and decremented `invoice.balance_due`
without locking. Concurrent voids could double-credit. Fix:
`with_for_update()` on both the payment and each invoice in the
allocation loop.

**Reconciliation drift.**
`sum(float(t.amount) ...)` over hundreds of cleared transactions
produced sub-cent float drift that made a truly-zero difference
display as `$0.00000001`. Replaced with `Decimal(str(...))`
arithmetic; convert to float only at the JSON boundary.

**Analytics AR aging consistency.**
The dashboard widget bucketed by **days-since-invoiced**; the
`/api/reports/ar-aging` endpoint bucketed by **days-past-due**. Same
data, different bucket → operator confusion. Analytics now matches
the report.

**Balance sheet — synthetic Net Income equity line.**
With no equity accounts holding transactions, the balance sheet
showed `Total Equity = 0` even though the books balanced. Now
computes net income from income/COGS/expense accounts and appends a
synthetic "Net Income (current period)" line to equity. A − L − E = 0.

**AR aging filter — include DRAFT.**
Aging was filtering `[SENT, PARTIAL]` only, hiding draft invoices with
open balances. Now `[DRAFT, SENT, PARTIAL]` at all 10 filter sites.

**Schema response types — Decimal not float.**
`BillResponse`, `BillLineResponse`, `POResponse`, `CreditMemoResponse`
were serializing money as `float`. Now `Decimal`. Round-trip stays
exact through the wire.

**Error handling — 4xx / 5xx mapping.**
`get_1099_pdf` was 500ing on a `ValueError` (not-found case); now
404. `restore_backup` always returned 500 regardless of cause; now
maps to 400 / 404 / 500. `low_stock_items` now surfaces oversold
inventory (`qty < 0`) regardless of reorder_point.

**IIF export — tab/newline sanitization.**
A vendor name with a `\t` in it would split that field into two on
import elsewhere. `_iif_clean()` now strips `\t\r\n` from every
field value before emission.

**Payroll input validation.**
`PayStubInput` schema rejects negative hours / overtime / deductions
/ gross_override at the boundary.

**IIF import — quantize SPL amounts.**
`_import_invoice` and `_import_estimate` now `_q(abs(...))` each SPL
amount before accumulating, matching the rounding semantics of
native invoice creation.

**Decompressed inventory restore audit, SSRF hardening, proxy
correctness** (batch 3 of the earlier enterprise eval) — see commits
`749b96e`, `f0c5816`, `87c0222`.

### Red-team pass on WC3D's Jinja2 XSS fix
WC3D's commit `ca6182f` enabled `autoescape=True` on the two Jinja2
Environments he found (`app/routes/public.py`,
`app/services/pdf_service.py`). A red-team sweep of every other
Jinja2 construction in `app/` turned up **one more spot** missing
the same fix:

- `app/services/email_service.py:139` — `SandboxedEnvironment()`
  (used to render admin-editable email templates with customer-
  supplied data injected as context). Fixed:
  `SandboxedEnvironment(autoescape=True)`.

- Same file, line 156–164 — when the file-based template fails, the
  fallback path was f-string-interpolating `invoice.customer.name`
  directly into an HTML body. Routed through `html.escape()` now.

Added `tests/test_jinja_autoescape_audit.py` — walks every
`Environment(...)` / `SandboxedEnvironment(...)` call in `app/`
(with a proper balanced-paren walker, since `Environment(loader=
FileSystemLoader(...))` defeats a naive `[^)]*` regex) and fails CI
if any one is missing `autoescape=`. The rule can't drift back.

Also verified the JS side: `toast()` uses `textContent`, so all
`toast(\`...${user.name}...\`)` calls are safe by construction;
`openModal()` uses `textContent` for the title (safe) and
`innerHTML` for the body (relies on per-call `escapeHtml()`, which
36 of 40 JS files use — the remainder don't render user-strings).
The broader JS-innerHTML-XSS class is a separate concern already
tracked under the CSP-unsafe-inline-cleanup item in `docs/todo.md`.

### Layout: `alembic/` → `migrations/`
Database migration scripts moved from `alembic/` to the more
conventional `migrations/` at the top level. `script_location` in
`alembic.ini` updated; references in CONTRIBUTING, PR template, and
docs all retargeted. The `alembic` CLI command itself is unchanged
(reads alembic.ini for its script_location), so `alembic upgrade
head` in `docker-entrypoint.sh` keeps working. Git tracked the moves
as renames, so blame history is preserved.

### Schema-wide date-collision fix (the rest of jake-378's pattern)
jake-378 previously fixed the `date: date` field-name-shadows-type
collision in `app/schemas/invoices.py` and `estimates.py` (commits
48cdb79, e12bbb1). A quick reproducer confirmed **pydantic 2.13 still
has the same bug**:

```python
class Update(BaseModel):
    date: Optional[date] = None   # Optional[<the field>] not Optional[date]
                                   # -> "Input should be None" on every value
```

Same pattern existed in **9 more schemas** (banking, bills, cc_charges,
credit_memos, deposits, journal, payments, purchase_orders,
time_entries) — applied jake's `from datetime import date as dt_date`
rename uniformly across all of them. Added
`tests/test_schemas_audit.py` to lock in the rule so the bug can't
drift back in via a new schema file. (296 tests now passing, up from
295.)

### PostgreSQL version doc alignment
Compose files (both dev and prod) already ship `postgres:17-alpine`,
but `README.md`, `INSTALL.md`, `docs/development.md`, and
`docs/operations.md` all said "PostgreSQL 16" or `brew install
postgresql@16`. Same lag-vs-reality pattern as the Python version
fix. Docs now match what's actually deployed (17).

### Dependency upgrade pass
Five hard-pinned (`==`) deps in `requirements.txt` were months behind.
Pins relaxed to floor-and-cap ranges so future patch/minor bumps land
without needing a release. All upgrades are stable 2.x → 2.x or
patch-only; no API churn expected. pip-audit on the new requirements
remains clean (zero known CVEs).

| Dep | Was | Now | Installed (verified) |
|---|---|---|---|
| `alembic` | `==1.13.3` | `>=1.16.0,<2.0` | 1.18.4 |
| `sqlalchemy` | `==2.0.35` | `>=2.0.40,<3.0` | 2.0.49 |
| `pydantic` | `==2.9.2` | `>=2.11.0,<3.0` | 2.13.4 |
| `pydantic-settings` | `==2.5.2` | `>=2.10.0,<3.0` | 2.14.1 |
| `uvicorn[standard]` | `==0.30.6` | `>=0.32.0,<1.0` | 0.47.0 |

Tests: 295 passing on the upgraded set (no source changes needed).

### Python version doc alignment
`README.md`, `INSTALL.md`, and `docs/development.md` all said "Python
3.12" or "3.12+", but the Dockerfile, every CI job, and the CVE
comments in `requirements.txt` reference Python 3.13. Docs now say
3.13 (the actual tested version); INSTALL.md notes that 3.12 may work
but isn't gated by CI.

### CRM-side UX additions
- **Customer Details modal** — clicking a customer row now opens a
  single-screen popout (no sub-tabs) with billing/shipping addresses,
  autosaving notes, attached reseller permits, recent invoices, and
  recent payments. Closes the "where do we put notes for everyone to
  see?" gap.
- **Reseller permits module** — new `#/reseller-permits` page with
  expiring-soon strip, per-state format validation (WA 9-digit, CA
  9-12, TX 11), copy-permit/business-name/tax-ID buttons, and a
  unified Verify workflow that opens the state's official lookup site
  in the default browser (`window.open('_blank', 'noopener,noreferrer')`
  after a confirm dialog) then stamps `last_verified_at` / disables
  with an inactive marker. Backend has CRUD + `/expiring` +
  `/validate-format` + `/mark-verified`. Pure record-keeping — there
  is no fake "API call" to the state; the operator does the lookup,
  we record the verification trail.
- **Admin Sign Out button** — topbar now has a dedicated logout button
  that POSTs `/api/auth/logout` and reloads to the splash page. The
  endpoint was live; only the button was missing.

### Test infrastructure
- **Bidirectional wiring audit** — `tests/test_wiring.py` already
  asserted every JS `API.*` call resolves to a route; it now also
  asserts every backend `/api/*` route has a JS caller (or is on the
  `_INTENTIONAL_BACKEND_ONLY` allowlist). The catch-all collector
  picks up template-literal paths (including paths assigned to a
  variable before `API.post(url, …)`), `href=`/`action=` attributes
  in JS-rendered HTML, and `window.open('/api/…')`. Pre-substitutes
  `${…}` blocks before regex matching so nested `encodeURIComponent`
  expressions don't break the path capture. Each allowlist entry now
  carries a comment explaining *why* the route has no SPA caller
  (admin-only, scheduled job, drill-down endpoint shadowed by the
  bundled `/dashboard` response, future UI tab, etc.).
- **Audit hook coverage in tests** — `conftest.py` was creating a
  fresh per-test session factory but never re-attaching the
  `after_flush` audit hook to it, so the entire audit-log mechanism
  was silently bypassed in every existing test. The fixture now calls
  `register_audit_hooks` on the per-test session factory. A new
  matrix test (`test_audit_log_covers_new_entities_but_skips_audit_tables`)
  asserts a ResellerPermit insert lands in `audit_log` and a
  PortalAccess insert does NOT (it's already an audit-flavored table).
- **`_SKIP_TABLES` curated** — `audit_log` was the only entry; added
  `portal_accesses`, `login_attempts`, `document_audits`, and
  `email_log` (every one is itself an audit/log table, and double-
  logging into `audit_log` would just add noise and create a future
  recursion footgun if any of them ever gains a trigger-set `id`).

### Payroll / HR UI additions
- **Portal-token admin view** — Employee Details > Portal Access now
  shows expires-at (red when <30 days), last-used-at, and a
  collapsible recent-access log pulled from `portal_accesses`.
- **PTO accrual editor** — `#/hr/pto` gained an Employee Accruals
  section with enroll-employee-in-policy form and per-row "Run Accrual"
  prompt. Closes the gap where admins had to enroll employees via curl.
- **E-Verify case tracking** — schema additions (`everify_status`,
  `everify_submitted_at`, `everify_closed_at`, `everify_notes`),
  GET/PUT `/api/employees/{id}/everify` endpoints, and a new section
  in the Employee Details modal with color-coded status. Pure
  record-keeping — the federal E-Verify submission still happens via
  the official portal or a vendor; this stores the case so DHS
  inspections find it in one place.

### Partial CSP tightening
- index.html's 11 inline `onclick=`/`oninput=` handlers moved to a new
  `app/static/js/bootstrap.js` that wires them via `addEventListener`
  after DOMContentLoaded. The static shell page now has zero inline
  handlers — would work under a stricter CSP today.
- `'unsafe-inline'` stays in `script-src` and `style-src` because the
  JS-rendered modal templates across the rest of the app still emit
  inline handlers + styles. Removing those is a multi-file refactor
  documented in `docs/todo.md`. Honest accounting added to
  `docs/security-hardening.md`.

### Polish
- `docs/release-checklist.md` section 4 (TLS) now mentions optionally
  submitting the domain to the HSTS preload list once TLS is locked in.

### Audit + ops automation
- **Portal access audit log** — new `portal_accesses` table records
  every authenticated and unauthenticated portal hit (employee_id, IP,
  truncated UA, path, success). Mirrors `LoginAttempt` and gives
  forensic queries something more granular than `portal_token_last_used`.
- **Encryption key rewrap CLI** — `python -m app.services.encryption
  rewrap` re-encrypts every bank-PII blob under the current key, so
  rotation can actually complete (transparent reads via PREV fallback
  was already shipped). Supports `--dry-run`.
- **Wiring audit as a unit test** — `tests/test_wiring.py` grep-and-
  resolves every JS `API.*` call against the registered FastAPI routes.
  Catches typos and stale paths automatically — CI fails when a JS
  caller goes nowhere.
- **End-to-end portal test** — single test walks the entire portal
  lifecycle (mint → claim → 5 cookieless pages → POST PTO → logout →
  cold-401 → force-expire → rotate → claim again).
- **Weekly `pip-audit` GitHub Action** — Sunday cron, opens a
  security-labeled issue on findings (de-duped), fails the workflow run.

### Frontend polish
- **Drag-and-drop document uploads** on Employee Details > Documents.
- **Portal logout button** in `portal/base.html` nav.
- **Branded portal favicon** — `/portal/favicon.ico` serves the
  employer's company logo so each customer's portal carries their own
  bookmark icon.

### Bug fix
- Pay-stub PDF was rendering accountable-plan reimbursements as
  positive line items in the **Deductions** table. Now they have their
  own **Additions to Net (non-taxable)** table above net pay. Net-pay
  math was always right; the display was confusing.

### Tax forms — PDFs, audit hashes, the works
- **WeasyPrint PDF endpoints** — `POST /api/payroll/forms/{w2,w3,940,941}/.../pdf`
  render real printable forms (Acme Co. branded, masked SSN, full box
  data). The existing JSON endpoints stay for future e-file integration.
- **Document audit hashes** — every tax-form PDF carries a SHA-256
  content hash and an audit ID in the footer. Backed by a new
  `document_audits` table with three lookup endpoints
  (`/api/document-audits`, `.../verify/{hash}`, etc.). An auditor with
  the PDF can recompute the hash and confirm authenticity against
  the trust-anchor row.

### Payroll / HR
- **Time-entry → pay-run auto-population** — the pay-run form now has
  a "Use approved time entries" checkbox + live-preview column showing
  unpaid approved hours per employee. Backend was already wired; only
  the frontend opt-in was missing.
- **PTO year-end carryover automation** — new
  `POST /api/pto/accruals/year-end-carryover?target_year=YYYY` endpoint
  caps every accrual at its policy `max_carryover` and resets YTD
  counters, returning a per-row before/after summary.
- **Portal cookie session** — after the first `/portal/{token}` claim,
  the token moves into a `HttpOnly Secure SameSite=Strict` cookie and
  every subsequent URL is cookieless. No more Referer leak, browser
  history, or shared-bookmark exposure. Backward-compat: emailed
  `/portal/{token}` links still work — they just redirect through the
  claim flow once.
- **Portal branding** — every page renders the employer's company name
  and logo in the header (was generic "Employee Portal").
- **State new-hire report PDF branding** — same treatment.

### Authentication / session hardening
- **Login attempt audit log** — new `login_attempts` table records
  every success and failure (IP, UA, timestamp). Catches the slow
  brute-force attacker who paces under the 5/min rate limit.
- **Session rotation on login** — `request.session.clear()` before
  issuing the auth flag, defense-in-depth against session fixation.
- **Idle session timeout** — sliding window via
  `SESSION_IDLE_TIMEOUT_SECONDS` (default 14400s = 4 hours). Sessions
  past the threshold get 401'd and cleared.

### Security
- **App-level `HTTPSRedirectMiddleware`** + HSTS (2-year, includeSubDomains,
  preload) when `FORCE_HTTPS=true`. Session cookie carries `Secure` flag
  in the same conditional.
- **Content-Security-Policy** — `frame-ancestors none`, `object-src
  none`, `form-action self`, Stripe origins allowlisted.
- **Startup fail-hard checks** (production only): refuses to start if
  `PAYROLL_ENCRYPTION_SECRET` is the dev default, `DATABASE_URL` lacks
  `sslmode`, or `FORCE_HTTPS=false`.
- **Portal token expiry** — 1-year hard + 90-day sliding idle. Expired
  tokens return `410 Gone`.
- **Portal headers** — `Referrer-Policy: no-referrer` and
  `Cache-Control: no-store` on every portal response.
- **Encryption key versioning** — bank PII ciphertext now prefixed with
  `v1:`. `PAYROLL_ENCRYPTION_SECRET_PREV` env var supports
  zero-downtime key rotation; decrypt tries current key first, then
  previous.
- **Per-endpoint rate limiting** — portal at 30/min GET / 10/min POST,
  joining the existing 5/min on login.

### Dependency CVE pass
Bumped requirements.txt to close known CVEs surfaced by `pip-audit`:
- `cryptography` — cap raised from `<44.0` to `<47.0`, floor `46.0.5`
  (closes PYSEC-2026-35, CVE-2024-12797, CVE-2026-26007, etc.)
- `fastapi` — bumped from `0.115.0` to `>=0.121.0,<0.122` to allow
  starlette `0.47+`
- New explicit `starlette>=0.47.2,<0.50` pin (closes CVE-2024-47874,
  CVE-2025-54121)
- New explicit `pyjwt>=2.10.0,<3.0` pin (override intuit-oauth's
  transitive 2.7.0 with known CVE)

`pip-audit -r requirements.txt` now reports **zero known
vulnerabilities**.

### Wiring fixes
Spider-web audit of every `API.*` call against every `@router.*`
handler caught four real breakages:
- 3× `API.delete()` typos (`API.del` is the actual export) — `employees.js`,
  `deductions.js`
- Missing `GET /api/pto/policies/{id}` and `PUT /api/pto/policies/{id}` —
  the policy-edit form was 404'ing
- `/approve` and `/reject` alias routes for the PTO `/decision` endpoint —
  the buttons were hitting non-existent paths

### Docs + repo conventions
- **`CONTRIBUTING.md`**, **`.github/PULL_REQUEST_TEMPLATE.md`**,
  **`.github/ISSUE_TEMPLATE/{bug_report,feature_request,config}.{md,yml}`** — the
  standard set this size of repo should have had.
- **`docs/hipaa-compliance.md`** — Security Rule mapping, 8-gap honest
  assessment, deployment recommendations.
- **`docs/security-hardening.md`** + **`docs/wiring-audit.md`** + **`docs/todo.md`** — engineering
  logs for the hardening pass, the wiring audit methodology, and the
  internal TODO scratchpad.
- README de-Phased / de-Tiered — that history now lives in this
  CHANGELOG file instead of cluttering the user-facing readme.

### Cleanup
- **Alembic revision collision fixed** — tier1 was sharing
  `f6a7b8c9d0e1` with the Phase 11 inventory migration. Renamed to
  `f7a8b9c0d1e2`; chain is now linear.
- `test_frontend_pages.py` moved from repo root to
  `scripts/integration_test_frontend.py` (it's a live-HTTP integration
  script, not a unit test).
- `app/templates/invoice_pdf_v2.html` deleted — added 5 weeks ago but
  never wired into `pdf_service.py`.
- `backups/` directory kept tracked (via `.gitkeep`) but contents
  gitignored so dumps don't accidentally land in commits.

### Test coverage
297 tests passing. Up from 119 at the start of this branch's work.
All previously-passing tests still pass.

### Docs reorganization
Root now keeps only `README.md`, `INSTALL.md`, `SECURITY.md`,
`CHANGELOG.md`, `CONTRIBUTING.md` (the conventional set). Everything
else moved into `docs/`.

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
- Tax-category mappings now reject nonexistent chart-of-account IDs before
  persistence instead of relying on backend-specific foreign-key failures.
- Pending-deposit results now report the remaining portion of a partially
  deposited source payment instead of repeating its full original amount.
- Purchase-order tax-rate-only edits now recompute tax and total, and updates
  reject unknown vendors or statuses before persistence.
- Recurring templates now reject unsupported or null frequencies and end dates
  before their start date on both creation and update instead of leaking a
  database integrity error.
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
