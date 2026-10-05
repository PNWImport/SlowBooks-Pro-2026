# Cross-layer review — September 16, 2026

Scope: the uncommitted 2.16.0 working tree incorporating upstream `719735e`.
This is a review of connections between layers, not a release certification.
The earlier 4,715-pass suite predates the chart-import intake and version bump.

## Findings resolved

### Resolved: invalid replacement import deactivated unrelated accounts

`app/services/chart_import.py:578` builds replacement deactivations even when
parsing yielded errors and no valid account rows. At line 705, those generated
rows satisfy the condition for applying the plan. Reproduced in an isolated
SQLite database with three unused non-control accounts: importing the following
with `replace=True, dry_run=False` returned an unknown-type error, reported
`dry_run=False`, and deactivated all three accounts:

```csv
Number,Name,Type
7103,Bad,nonsense
```

Resolution: any parse or row error keeps the operation in dry-run mode and
writes nothing. The regression verifies every account's active state is
unchanged. Imports are atomic rather than partially applying valid-looking rows.

### Resolved: applying an import could use inputs that were never previewed

`app/static/js/app.js:337` retains the mutable form; line 376 reads its current
file and replacement checkbox. Reproduced by executing the actual controller
in Node with mocked DOM/transport: preview posted `reviewed.csv` with
`dry_run=1&replace=0`; after changing the controls, Import posted
`unreviewed.csv` with `dry_run=0&replace=1`, without another preview.

The server also computes a fresh plan for each request; it does not verify
that the database still matches the preview. The UI's promise to apply exactly
the reviewed plan is therefore stronger than its implementation.

Resolution: the preview returns a hash of its public plan. Apply requires that
hash, recomputes the plan while locking account rows on PostgreSQL, and returns
409 if the chart or plan changed. The controller binds approval to the same File
object and Replace value, invalidates it on input changes, and ignores stale
preview responses. Error plans never enable the Apply button.

### Resolved: imported type changes could violate bank-account invariants

At `app/services/chart_import.py:503`, type changes are planned separately from
`bank_kind`; application at line 650 leaves an existing flag untouched.
Reproduced by importing an unused account as `bank`, then as `expense`:
the stored result is `account_type=expense, bank_kind=bank`. The ordinary account
route rejects this combination, but the importer bypasses that validation.
Bank pickers use the flag, so the inconsistent account remains bank-selectable.

Resolution: planning validates the effective type/flag pair. A permitted type
change clears an incompatible existing bank designation; a history/control
account whose type must stay produces a row error instead of acquiring an
invalid designation.

### Resolved: parent-only updates were silently ignored

Parent resolution at `app/services/chart_import.py:560` occurs after the action
is classified. An otherwise unchanged existing account remains `skip`, and the
apply loop does not set its resolved parent. Reproduced with existing account
6101 and existing parent 1000: a CSV changing only Parent reported zero updates,
one skip, and left `parent_id=None`.

Resolution: the parser records whether the Parent column was supplied. A changed
parent is an update, and an explicitly blank Parent clears the relationship;
omitting the column leaves it unchanged.

### Resolved: import accepted cycles in the account hierarchy

`app/services/chart_import.py:675` only prevents direct self-parent assignment.
Two new rows with reciprocal Parent numbers persisted a two-account cycle:

```csv
Number,Name,Type,Parent
7101,First,expense,7102
7102,Second,expense,7101
```

Resolution: planning builds the effective graph across existing and new rows
and rejects any cycle before writes. The reciprocal-parent reproduction now
returns a cycle error and creates neither account.

## Additional policy observation

An explicit `Active=false` can deactivate a control account via the importer.
This was reproduced, but the ordinary account route also permits deactivation;
it is not classified here as a newly introduced authorization bypass. Reconcile
the import UI's "control accounts stay" wording with explicit Active semantics.

## Verification and limits

- Wiring, unauthenticated-route contract, chart import, account schema,
  ledger/report reconciliation invariants and inline-handler parsing:
  **583 passed, 2 skipped**. The skips were live PostgreSQL parity tests.
- Deployment configuration, private upload/attachment access, template secrets,
  PDF fetching, session secrets and migration source/repair helpers:
  **119 passed**.
- Backend-only authorization, accounting concurrency, audit chains/signatures,
  money precision, invoice posting/editing, bank reconciliation, schema repair
  and subprocess/template safety: **257 passed, 20 skipped**. Skips were
  documented public endpoints and unavailable PostgreSQL/SQLite row-lock cases.
- Repeated the environment-dependent gates against a disposable PostgreSQL 17
  instance: **38 passed, 5 skipped**. Empty and legacy migration-to-model parity,
  accounting/audit concurrent writes, bank row locks and schema repair passed.
  The remaining five skips are deliberate SQLite row-lock variants. These
  groups overlap; their counts are execution results, not unique test totals.
- Repaired chart importer: **21 passed** with **100% statement coverage
  (433/433)**. Frontend controllers: **32 passed**. Black: **722 files clean**; Ruff and
  whitespace checks passed. Alembic reports one head, `ac14bd25ce36`.
- Expanded route/auth/wiring, account-schema, ledger invariant, CSV/IIF/QBO and
  migration-parity gate: **682 passed, 6 skipped**. Four skips are deliberately
  public provider/OAuth endpoints; two are the PostgreSQL parity variants that
  passed separately against the disposable PostgreSQL 17 instance above.
- Database findings above used only a new in-memory database; UI reproduction
  used mocked transport. No user company data was touched.

All five findings are resolved with regression coverage. This review did not
execute hosted CodeQL, native signed bundles,
live payment/provider operations, or a new whole-product browser crawl.
