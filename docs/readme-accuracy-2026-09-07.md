# README accuracy check — 2026-09-07

> **Superseded — this branch has since merged `origin/main` (345 commits).**
> Findings below describe the branch *before* that merge and are kept as a
> point-in-time record, not as a current description of the tree. What the
> merge changed is summarised at the end of this file.

Every claim below was checked against the code on
`claude/main-branch-protection-2tqh90` @ `e2146ff`. Findings are ordered by
how much they'd mislead a reader, not by how easy they are to fix.

**Nothing here is a bug in the software.** These are places where the
README describes something other than what ships.

---

## Wrong

### 1. "250+ bullets" in the feature catalog — actual count is 144

> "Full feature catalog (250+ bullets across every module) lives in
> **[docs/features.md](docs/features.md)**"

`grep -c "^- \|^  - " docs/features.md` → **144**.

Either the count was aspirational or the catalog shrank. 144 is still a
lot; the fix is to say 140+, or drop the number — a count in prose has to
be re-checked on every edit, and this one wasn't.

### 2. "seven providers" followed by a list of six

Appears **twice** (lines 34 and 52):

> "…for any of seven providers (xAI Grok, Groq, Cloudflare Workers AI,
> Anthropic Claude, OpenAI, Google Gemini)"

That parenthetical names **six**. `PROVIDERS` in
`app/services/ai_service.py` has **seven** keys — the seventh is
`cloudflare_worker`, the self-hosted gateway, which the README describes
separately a few lines later ("or against a **Cloudflare Worker you host
yourself**"). So the number is right and the list is short by one, which
reads as a typo either way.

Worth noting: `main` has since added a custom OpenAI-compatible provider
and updated its README to **eight**. This branch is at seven. Whichever
lands first should make the two agree.

### 3. Tech stack says Python 3.13 — the suite has only ever run on 3.11

> "Python 3.13 + FastAPI on PostgreSQL 17…"

`Dockerfile` (`FROM python:3.13-slim`) and all four CI jobs
(`python-version: "3.13"`) do target 3.13, so the claim matches intent.
But the container these 1369 tests ran in is **Python 3.11.15**. Nothing
failed, but "runs on 3.13" is currently an untested assertion. One CI run
settles it.

`INSTALL.md` is more careful and says the right thing already: *"CI gates
against 3.13; older 3.12 may work but isn't tested."*

---

## Stale but harmless

### 4. Screenshots predate the current UI

The README embeds five screenshots (dashboard light/dark, invoices,
analytics, inventory, duplicate detection). The dashboard shots are from
before the payroll/HR nav section existed — the sidebar in the image has
noticeably fewer entries than the app now renders. Not wrong, just old.

### 5. "50-account Chart of Accounts (Contractor template)"

Could not verify from `scripts/seed_database.py` — the seed builds accounts
programmatically rather than from a countable literal list, so the number
isn't checkable by inspection. Left alone rather than guessed at; if the
number matters, count it at runtime after a fresh seed.

---

## Checked and correct

Recorded so nobody re-checks these later:

| Claim | Verdict |
|---|---|
| "Database schema — 68 tables" (doc index) | **Correct.** `Base.metadata` has exactly 68. Fixed earlier this session — it previously said 55. |
| "Argon2id passwords" | **Correct.** `app/services/auth.py` uses `argon2.PasswordHasher`. |
| "Fernet at-rest encryption with versioned ciphertext (clean key rotation)" | **Correct.** Ciphertext is stored as `v1:gAAAAA…`; `rewrap_all` handles rotation, and `tests/test_encryption_coverage.py` now proves the values are ciphertext on disk. |
| "SHA-256 content hash and an audit ID printed in the footer" | **Correct**, and now stronger than described — `document_audits` is a linked hash chain with signed, exportable checkpoints, which the README's "Wait — it does *that*?" section undersells. |
| "startup checks that fail hard on critical misconfig" | **Correct.** `_run_startup_security_checks()` raises on the dev encryption key against a real DB, missing TLS on `DATABASE_URL`, and `FORCE_HTTPS=false` in production. |
| "Boots refuse to lie to you" (wiring self-check before uvicorn binds) | **Correct.** In `docker-entrypoint.sh`, gated on pytest being installed. |
| "Self-hosted Chart.js (no CDN; LAN-deployable)" | **Correct.** `app/static/js/chart.umd.js` is vendored. |

---

## Suggested edits

Smallest set that makes the README true:

1. `250+ bullets` → `140+ bullets`, or drop the number.
2. Add the seventh provider to both parentheticals, or change "seven" to
   "six providers plus your own Cloudflare Worker". Reconcile with `main`'s
   eight.
3. Leave the Python 3.13 claim, but run CI once on 3.13 so it's backed.
4. Optional: refresh the dashboard screenshots, and consider mentioning
   the audit *chain* rather than just per-document hashes.

---

## Post-merge status (appended after merging `origin/main`)

Findings 1 and 2 are **resolved by the merge**, not by an edit here: the
README now says "eight providers" (which matches `ai_service.PROVIDERS`)
and no longer claims a bullet count. Finding 3 (Python 3.13 asserted but
only ever exercised on 3.11) still stands — one CI run settles it.
