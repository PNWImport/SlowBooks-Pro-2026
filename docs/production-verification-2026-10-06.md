# Production verification — October 6, 2026

Local record. Nothing here was pushed, and no PR was opened. This is the
fix log for the verification pass made after the upstream 2.19.0 intake and
the October 5 payroll work: the app was driven the way production runs it,
every frontend call was exercised, and what that found was fixed and proven.

Starting point: the suite was green (6,538 passed) and CI was green. The
point of this pass was that a green suite does not show that the frontend and
backend agree, or that the app survives PostgreSQL under parallel requests.
It did not: the pass found defects the suite could not see, listed below.

## How it was run

- **Fresh PostgreSQL 17 built by `alembic upgrade head`**, the way a deployment
  builds it: head `b7fringe2026105`, 101 tables. Three isolated instances
  (separate databases and ports), booted with production-style secrets.
- **Static contract check:** every API call the frontend can make (419
  distinct calls in `app/static/js` and `index.html`) matched against the
  619 registered operations. The unmatched ones were URLs built at run time
  (`/api/reports/${x}/pdf`, `/api/iif/export/${x}`, `/api/csv/import/${entity}`),
  which a regex cannot resolve; the live runs below resolved each real value.
- **Page walk (real Chromium, seeded data):** all 74 SPA routes, each
  report/PDF/CSV/IIF/export download (about 125, all 200 with the right
  content type, every PDF starting `%PDF`), every read-only control and modal.
- **Workflow driver (real Chromium, real forms):** invoices, payments,
  deposits, credit memos, voids, estimates; bills, Pay Bills, vendor credits,
  purchase orders; bank import, review, transfers, reconciliation; payroll
  from employee to paystub, retro, termination, W-2/941/940, ACH, contractor
  runs and 1099; users and roles; settings. Followed by integrity checks:
  trial balance, balance sheet, A/R and A/P against their subledgers, journal
  balance, inventory against movements, payroll liabilities against paystubs.
- **Fuzz and role matrix:** 485 operations, about 7,800 requests with valid,
  empty and hostile bodies (NUL bytes, NaN/Infinity, 1e30, year 9999, 200,000
  character strings, bad ids); 259 mutating calls replayed as read-only,
  bookkeeper, unauthenticated and API token; 16 concurrency races.
- **Code review of the October 5 payroll diff** (78 modified and 17 new files):
  10 findings, each checked against the code before acting.

## Findings and what was done

Severity as the sweeps rated it. "Proven" means a regression test that fails
on the old code and passes on the fix, or a live re-run where the bug only
shows on PostgreSQL.

### Money and ledger correctness

| Finding | Cause | Fix | Proof |
|---|---|---|---|
| Depositing one receipt four times in parallel posted four deposits (Checking +308 for a 77.00 receipt) | A `FOR UPDATE` re-read after the lock returned the object loaded before the wait, so the "already deposited?" check read stale data. Upstream's code, since the local `populate_existing()` was superseded in the intake | Every locked read refreshes what it locks (`app/database.py`), which closes the whole class, not one site; it flushes first so unsaved changes are kept | Live races, 8 parallel × 3 runs: one success, Checking +77, `tests/test_locked_reads.py` |
| Writing off one invoice three times in parallel created three credit memos (A/R −300) | No row lock before the balance was read | Invoice locked first; the memo-number retry uses a savepoint so it cannot drop the lock | Live races: one success, A/R −100 |
| Parallel payments and bills answered 500 `DeadlockDetected` (5 of 6, 4 of 6) | A request inserts child rows (taking `FOR KEY SHARE` on the accounts) and then asks for `FOR UPDATE` on the same rows; two requests each wait to upgrade a lock the other holds | `lock_accounts` takes `FOR NO KEY UPDATE`, which does not conflict with key-share and still serializes balances | Live races, 12 parallel × 3 runs: all succeed, 0 deadlocks in the log |
| Four bills with one number entered at once created two | Check-then-insert with no unique index | New bills for one vendor serialize on the vendor row | Live races: exactly one created |
| Contractor payments debited 6130 Workers Compensation Insurance; the P&L and Schedule C line 15 showed them as insurance | The code assumed 6130 was a contractor account; in the seeded chart it is workers' comp | The account is found by name (contractor/contract), else the generic expense account | `test_contractor_pay_does_not_post_to_the_seeded_workers_comp_account` |
| An item created with stock got no cost, no movement and no journal entry; sales posted $0 of COGS; on-hand disagreed with the movement ledger | `create_item` stored the quantity on the row alone (identical in upstream) | Opening stock becomes a movement and Dr Inventory / Cr Opening Balance Equity; refused with a clear message if there is no inventory account | `test_an_item_created_with_stock_is_valued_and_costs_its_sales` |
| Cancelling a retro-pay draft left the pay raise it had staged, with no arrears paid | Staging sets the rate at once; cancel did not undo it | The draft records the previous rate and cancel restores it only if the rate is still the staged one | `test_cancelling_a_retro_draft_takes_back_the_raise_it_staged` |
| 1099 summary report showed $315.50 where the 1099-NEC form showed $1,815.50 | The summary ignored contractor runs | Shares the form's source of truth; voided bill payments excluded | `test_report_source_agreement.py` |
| Dashboard Total Payables $300 against A/P aging $250 | The card ignored an unapplied vendor credit | Uses the A/P aging total | same file |

### Payroll rules (the two October 5 integrity rules and GTL)

| Finding | Fix | Proof |
|---|---|---|
| A termination PTO payout draft is blocked once the final paycheck is paid first, and Terminate cannot be run twice, so the payout could not be paid | `POST /api/employees/{id}/pto-payout` stages it again, by default dated on or after the last paid check; a "PTO payout" button on terminated employees; the blocked-draft message names the way out. Refused if a payout is already staged or already paid (processing a payout does not use up the PTO balance, so staging again would pay it twice) | `tests/test_pto_payout_restage.py` |
| Drafts staged before reservations were recorded could be neither processed nor cancelled | Cancel refunds the year-to-date amounts, which staging always added, so they are exactly known. A loan-tracking code makes the owner ambiguous: cancel then needs `acknowledge_unverified_loans`, lists those balances and leaves them for review, and never guesses. The Cancel button shows that prompt | two tests in `tests/test_staged_payroll.py` |
| Seeded group-term life blocked payroll for anyone enrolled with an employer amount, and could not be classified as taxable | New `reported_only` classification: payroll leaves it out of wages and does not block it. The seeded `GTL` code ships that way. Unclassified codes still block, and the message names the way out | `tests/test_payroll_taxable_fringe.py` |
| A corrupted taxable-fringe snapshot raised an opaque `InvalidOperation` | Becomes the named "Invalid immutable taxable employer contribution" error | parametrized test in the same file |

### Input hardening (500 → 4xx)

About 58 endpoints answered 500 on hostile input on PostgreSQL (SQLite is
lenient, so the suite never saw them). Almost all were a few systemic gaps,
fixed once:

- **NUL byte** in any text, including the pre-login `POST /api/auth/login`:
  rejected in `StrictModel` (422).
- **NaN, Infinity, 1e999** amounts: rejected in `StrictModel`. Before, a NaN
  rate was committed and then every `GET /api/workers-comp/rates` answered 500.
- **Dates outside 1900–2200** (a year 9999 reached 22 posting endpoints and
  overflowed date arithmetic on invoices and bills): rejected in `StrictModel`
  and again in `check_closing_date`, which nearly every posting route calls.
- **`year` outside 1900–2200** in a path or query (about 20 tax, payroll and
  report routes): one app-level check, 422. `quarter` stays with the routes
  that already refuse it with 400.
- **Values the database refuses** (over-long text, numbers too large, a bad
  enum filter such as `?status=-1`): mapped to 422 without echoing the value.
- **Route-level:** invoice email with no recipient (now defaults to the
  customer's address, else 400); deleting a recurring invoice that has
  generated invoices (409, "make it inactive"); a non-OFX upload (400); a batch
  payment with a bad date (422); a missing `pg_dump` (503).
- **Authorization:** claiming or removing the SimpleFIN bank-feed credential
  is administrator-only; a bookkeeper can still run the daily sync.

Proof: `tests/test_hostile_input_hardening.py` (21 cases) and
`tests/test_robustness_fixes.py` (15 cases, 10 of which fail on the old code
when the route fixes are reverted), and a 112-case replay of the fuzz categories against the fixed instance:
**0 server errors** (the one 503 is the intended missing-`pg_dump` answer),
0 tracebacks in the server log.

### Reports, exports and UI

Fixed, each with a regression test: the P&L-by-class totals row (COGS and gross
profit were blank); the Schedule C CSV wrote a net loss as the text `'-5220.53`
(only plain signed decimals now skip the injection guard; hostile text is
still neutralised); an ACH file with zero entries was delivered as success
(now a 400, payroll and contractor); a benefit rate ignored the form's
Effective-from (now sent, and a pay run that drops an enrolled benefit for want
of a rate now warns); terminated employees can be included in a pay run for
work up to their termination date; the Terminate dialog's counts were
mislabelled; Reconcile discarded a typed balance when one was already open
(now says so and resumes it); there was no way to restore an excluded bank
line or unmatch a matched one (a "Handled statement lines" card, with the
reason shown where unmatch is not allowed); the garnishment form had no agency
fields. Earlier in the same pass, the e-file and COBRA download toasts that
printed `[object Object]` were changed to the shared error text.

### A defect this pass introduced, and caught

The first version of the lock-refresh above discarded unsaved in-memory
changes: a credit-memo void applied to one invoice twice lost its first
subtraction. The full suite caught it (`test_credit_apply_edges_and_void_restores_invoice`).
The refresh now flushes first, as `lock_accounts` always has, and
`tests/test_locked_reads.py` pins both halves: unsaved changes are kept, and a
change made by another transaction is seen. The live races were re-run
afterwards and still pass.

## Evidence

| Check | Result |
|---|---|
| Full suite, Linux with PostgreSQL 17 attached (as CI's Linux job runs it) | **6,617 passed, 0 failed, 21 skipped** (native OCR and browser-only cases) |
| Frontend Node tests | 6 files, all pass |
| Black and Ruff (CI's exact scope, 943 files) | clean |
| Alembic | single head `b7fringe2026105`; builds from empty to head |
| Browser walk of all 74 routes, final code | 0 page errors, 0 `undefined`/`NaN` text. The remaining console lines are expected: AI/SMTP not configured, a blank-form validation message, the e-file transmitter-code warning, and the Intuit site's own errors when the QuickBooks connect button was followed offline |
| Concurrency races on the final code | exactly one winner each; ledger moved once; 0 deadlocks |
| Hostile-input replay on the final code | 112 cases, 0 server errors |

Hosted CI ran on the pushed branch before this pass (all five jobs green at
`1a5d90f`). The changes in this record are local and have not been through
hosted CI.

## Not exercised

Backup list, download and restore (no `pg_dump` on the test host); sending
real email; payment providers; QuickBooks Online and SimpleFIN against live
services; OCR with native tools; e-sign; PTO payout over a real term; 401(k)
tiered match; states other than the ones seeded; nonprofit mode; a signed
Windows or macOS build. The page walk did not press save/delete/void/send
buttons on the UI (the workflow driver did, for the money-moving flows).

## Open decisions (not defects; need a choice)

- **ACH access for bookkeepers:** the `can_access_bank_details` flag has no
  effect because `/api/payroll` is administrator-only. Recorded in
  [todo](todo.md#open-decisions--october-6).
- **Logout does not revoke the session cookie:** a copied cookie stays valid
  until it expires (signed cookie, no server-side session state). Fixing it
  means server-side session state and "sign out everywhere" semantics.
- **Garnishment "Mark Remitted" is register-only:** it posts no journal entry,
  so liability 2370 keeps the amount. Posting Dr 2370 / Cr bank needs a bank
  account parameter and a decision about checks entered elsewhere.
- **The final check for a terminated employee carries no benefit deductions**,
  because Terminate deactivates the employee's benefit assignments.
- **Smaller items the sweeps listed and nobody has decided on:** draft invoices
  post to the ledger and stock at once; a zero-total invoice creates an empty
  journal entry; the Form 941 dropdown defaults to Q1; attachment responses
  expose the internal `stored_files/N` path; 36 PUT endpoints accept an
  all-`null` body as a no-op.
